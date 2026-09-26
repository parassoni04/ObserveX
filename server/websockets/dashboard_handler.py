"""
Dashboard WebSocket Handler
============================

Handles the WebSocket lifecycle for dashboard (browser) connections:
1. Authenticate via JWT token in query parameter
2. Register in ConnectionManager with organization scope
3. Handle subscription/unsubscription to device telemetry
4. Send initial cached metrics for subscribed devices

Authentication:
- Dashboard connects to /ws/v1/dashboard?token=<jwt_token>
- Server decodes JWT and verifies user
- On failure: close with 1008 (Policy Violation)
- On success: register with organization_id for scoped broadcasts
"""
import json
import jwt as pyjwt
from fastapi import WebSocket, WebSocketDisconnect, Query

from server.config import settings
from server.database import get_session
from server.models import User
from server.authorization import check_device_access
from server.websockets.manager import connection_manager
from server.security.audit_logger import log_audit, ACTIONS
from server.logging import get_logger

logger = get_logger("ws_dashboard")


async def dashboard_websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(default=""),
):
    """Dashboard WebSocket endpoint."""
    # ── Step 1: Authenticate JWT ──
    user_id = None
    organization_id = None

    try:
        payload = pyjwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM],
        )
        user_id = int(payload.get("sub", 0))
        organization_id = payload.get("org_id")
    except Exception:
        pass

    if not user_id:
        await websocket.accept()
        await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=1008)
        await log_audit(
            ACTIONS["DASHBOARD_AUTH_FAILED"],
            actor_type="user",
            detail="Dashboard WS auth failed: invalid token",
            result="denied",
        )
        return

    # Verify user exists and is active
    async with get_session() as db:
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.accept()
            await websocket.send_json({"type": "error", "message": "User not found or inactive"})
            await websocket.close(code=1008)
            return
        organization_id = user.organization_id

    await websocket.accept()

    # ── Step 2: Register ──
    connection_manager.register_dashboard(websocket, user_id, organization_id)

    await log_audit(
        ACTIONS["DASHBOARD_CONNECTED"],
        actor_type="user", actor_id=str(user_id),
        organization_id=organization_id,
    )

    # ── Step 3: Message loop ──
    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                await websocket.send_json({"type": "error", "message": "Invalid JSON"})
                continue

            action = msg.get("action")
            device_id = msg.get("device_id")

            if action == "subscribe" and device_id:
                # Verify user has access to this device
                async with get_session() as db:
                    has_access = await check_device_access(user, device_id, db)
                if has_access:
                    connection_manager.subscribe_dashboard(websocket, device_id)

                    # Send cached data immediately
                    cached = connection_manager.latest_metrics.get(device_id)
                    if cached:
                        await websocket.send_json({
                            "type": "telemetry",
                            "device_id": device_id,
                            "payload": cached,
                        })

                    # Send cached processes
                    procs = connection_manager.latest_processes.get(device_id)
                    if procs:
                        await websocket.send_json({
                            "type": "processes",
                            "device_id": device_id,
                            "payload": procs,
                        })

                    await websocket.send_json({
                        "type": "subscribed",
                        "device_id": device_id,
                    })
                else:
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Access denied for device {device_id}",
                    })

            elif action == "unsubscribe" and device_id:
                connection_manager.unsubscribe_dashboard(websocket, device_id)
                await websocket.send_json({
                    "type": "unsubscribed",
                    "device_id": device_id,
                })

            elif action == "get_online":
                # Return online device IDs for this organization
                online = connection_manager.get_online_device_ids_for_org(organization_id)
                await websocket.send_json({
                    "type": "online_devices",
                    "device_ids": online,
                })

            else:
                await websocket.send_json({
                    "type": "error",
                    "message": f"Unknown action: {action}",
                })

    except WebSocketDisconnect:
        logger.info("Dashboard disconnected: user_id=%s", user_id)
    except Exception as e:
        logger.error("Dashboard WS error for user_id=%s: %s", user_id, e)
    finally:
        connection_manager.unregister_dashboard(websocket)
