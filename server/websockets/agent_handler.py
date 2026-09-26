"""
Agent WebSocket Handler
=======================

Handles the WebSocket lifecycle for agent connections:
1. Authenticate the agent via query parameter token
2. Send auth_success message
3. Enter message loop — handle heartbeat, telemetry, command_result
4. Track heartbeat state for timeout detection

Authentication:
- Agent connects to /ws/v1/agent/{device_id}?token=<api_key>
- Server verifies device_id exists and credential matches
- On failure: close with 1008 (Policy Violation)
- On success: register in ConnectionManager and begin message loop

Message types handled:
- heartbeat → heartbeat_ack
- telemetry → telemetry_ack + broadcast to dashboards + update DB
- command_result → update CommandLog status
"""
import asyncio
import datetime
import json
from fastapi import WebSocket, WebSocketDisconnect, Query
from sqlalchemy import update

from server.database import get_session
from server.auth.device_auth import verify_device_credential
from server.websockets.manager import connection_manager
from server.models import Device, MetricSnapshot
from server.security.audit_logger import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("ws_agent")


async def agent_websocket_endpoint(
    websocket: WebSocket,
    device_id: int,
    token: str = Query(default=""),
):
    """
    Agent WebSocket endpoint. Handles the full lifecycle:
    auth → heartbeat/telemetry loop → disconnect cleanup.
    """
    # ── Step 1: Authenticate ──
    async with get_session() as db:
        device = await verify_device_credential(device_id, token, db)

    if not device:
        logger.warning("Agent WS auth failed: device_id=%s", device_id)
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "Authentication failed", "code": "AUTH_FAILED"})
        await websocket.close(code=1008)
        await log_audit(
            ACTIONS["AGENT_AUTH_FAILED"],
            actor_type="agent", actor_id=str(device_id),
            detail=f"WS authentication failed for device_id={device_id}",
            result="denied",
        )
        return

    await websocket.accept()

    # ── Step 2: Register connection ──
    connection_manager.register_agent(websocket, device_id, device.organization_id)

    # Update device status in DB
    async with get_session() as db:
        await db.execute(
            update(Device)
            .where(Device.id == device_id)
            .values(is_online=True, status="active", last_seen=datetime.datetime.utcnow())
        )
        await db.commit()

    # Send auth success
    await websocket.send_json({
        "type": "auth_success",
        "device_id": device_id,
        "organization_id": device.organization_id,
    })

    await log_audit(
        ACTIONS["AGENT_CONNECTED"],
        actor_type="agent", actor_id=str(device_id),
        organization_id=device.organization_id,
        target_type="device", target_id=str(device_id),
    )

    # ── Step 3: Message loop ──
    _metric_write_counter = 0
    _metric_write_interval = 5  # Write every Nth telemetry to DB

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            msg_type = msg.get("type")

            if msg_type == "heartbeat":
                connection_manager.touch_agent_heartbeat(device_id)
                # Update last_seen in DB
                async with get_session() as db:
                    await db.execute(
                        update(Device)
                        .where(Device.id == device_id)
                        .values(last_seen=datetime.datetime.utcnow())
                    )
                    await db.commit()
                await websocket.send_json({
                    "type": "heartbeat_ack",
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                })

            elif msg_type == "telemetry":
                payload = msg.get("payload", {})
                if not isinstance(payload, dict):
                    await websocket.send_json({"type": "error", "message": "Telemetry payload must be a dict"})
                    continue

                # Extract processes if present
                processes = payload.pop("processes", None)
                if processes and isinstance(processes, list):
                    connection_manager.update_processes(device_id, processes)

                # Broadcast to dashboards and cache
                await connection_manager.broadcast_telemetry(device_id, payload)

                # Periodically persist to database
                _metric_write_counter += 1
                if _metric_write_counter >= _metric_write_interval:
                    _metric_write_counter = 0
                    try:
                        async with get_session() as db:
                            db.add(MetricSnapshot(
                                device_id=device_id,
                                organization_id=device.organization_id,
                                timestamp=datetime.datetime.utcnow(),
                                metrics=payload,
                            ))
                            await db.execute(
                                update(Device)
                                .where(Device.id == device_id)
                                .values(last_seen=datetime.datetime.utcnow())
                            )
                            await db.commit()
                    except Exception as e:
                        logger.error("Failed to persist metrics for device=%s: %s", device_id, e)

                await websocket.send_json({"type": "telemetry_ack"})

            elif msg_type == "command_result":
                cmd_id = msg.get("command_id")
                cmd_status = msg.get("status", "unknown")
                cmd_output = msg.get("output", "")

                if cmd_id:
                    try:
                        from server.models import CommandLog
                        async with get_session() as db:
                            cmd = await db.get(CommandLog, cmd_id)
                            if cmd and cmd.device_id == device_id:
                                cmd.status = "success" if cmd_status == "success" else "failed"
                                cmd.result_output = str(cmd_output)[:2000]
                                cmd.completed_at = datetime.datetime.utcnow()
                                await db.commit()

                        await log_audit(
                            ACTIONS["COMMAND_RESULT"],
                            actor_type="agent", actor_id=str(device_id),
                            organization_id=device.organization_id,
                            target_type="command", target_id=str(cmd_id),
                            detail=f"status={cmd_status}",
                        )
                    except Exception as e:
                        logger.error("Failed to update command result: %s", e)

                # Forward result to dashboards
                await connection_manager.broadcast_to_dashboards(device_id, {
                    "type": "command_result",
                    "device_id": device_id,
                    "command_id": cmd_id,
                    "status": cmd_status,
                    "output": cmd_output,
                })

            elif msg_type == "events":
                events = msg.get("events", [])
                if isinstance(events, list):
                    connection_manager.device_events[device_id] = events

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        logger.info("Agent disconnected: device_id=%s", device_id)
    except Exception as e:
        logger.error("Agent WS error for device_id=%s: %s", device_id, e)
    finally:
        # ── Step 4: Cleanup ──
        connection_manager.unregister_agent(device_id)

        async with get_session() as db:
            await db.execute(
                update(Device)
                .where(Device.id == device_id)
                .values(is_online=False, status="offline", last_seen=datetime.datetime.utcnow())
            )
            await db.commit()

        await log_audit(
            ACTIONS["AGENT_DISCONNECTED"],
            actor_type="agent", actor_id=str(device_id),
            organization_id=device.organization_id,
            target_type="device", target_id=str(device_id),
        )
