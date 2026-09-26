"""
ObserveX Agent — HTTP + WebSocket Communication.

Uses the new structured WebSocket protocol with message types.
All messages to/from the server include a "type" field:
  Agent → Server: heartbeat, telemetry, command_result
  Server → Agent: auth_success, heartbeat_ack, telemetry_ack, command, error
"""
import asyncio
import json
import datetime
import httpx
import websockets
from typing import Optional, Any
from agent.config import agent_settings


class AgentSender:
    """Handles HTTP REST and WebSocket communication with the ObserveX server."""

    def __init__(self):
        self._cfg = agent_settings
        self.device_id: Optional[int] = self._cfg.device.device_id
        self._ws: Optional[Any] = None
        self._pending_commands: list[dict] = []
        self.auth_rejected: bool = False

    @property
    def _server_url(self) -> str:
        return self._cfg.server.url.rstrip("/")

    @property
    def _headers(self) -> dict:
        """Authorization headers for HTTP requests."""
        cred = self._cfg.device.credential
        if cred:
            return {"Authorization": f"Bearer {cred}"}
        return {}

    async def _post(self, path: str, payload: dict, params: dict | None = None, timeout: float = 10.0):
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=self._cfg.network.verify_ssl,
        ) as client:
            resp = await client.post(
                f"{self._server_url}{path}",
                json=payload,
                params=params,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def enroll(self, enrollment_code: str, hostname: str, os_name: str, os_version: str) -> dict:
        """Enroll device using an enrollment code via the new endpoint."""
        data = await self._post("/api/v1/enrollment/enroll", {
            "enrollment_code": enrollment_code,
            "hostname": hostname,
            "os_name": os_name,
            "os_version": os_version,
        })
        self.device_id = data["device_id"]
        return data

    async def send_heartbeat(self):
        if self.device_id is None:
            return
        await self._post("/api/v1/agent/heartbeat", {
            "device_id": self.device_id,
        }, timeout=5.0)

    async def send_static_info(self, info: dict):
        if self.device_id is None:
            return
        await self._post(
            "/api/v1/agent/static-info", info,
            params={"device_id": self.device_id},
            timeout=15.0,
        )
        print(f"[Agent] Static info uploaded for device_id={self.device_id}")

    async def send_software_list(self, software: list[dict]):
        if self.device_id is None:
            return
        await self._post(
            "/api/v1/agent/software", {"software": software},
            params={"device_id": self.device_id},
            timeout=30.0,
        )
        print(f"[Agent] Software list uploaded ({len(software)} items)")

    async def send_event_logs(self, events: list[dict]):
        if self.device_id is None:
            return
        await self._post(
            "/api/v1/agent/events", {"events": events},
            params={"device_id": self.device_id},
            timeout=30.0,
        )
        print(f"[Agent] Event logs uploaded ({len(events)} events)")

    # ── WebSocket Methods (Structured Protocol) ──

    async def connect_ws(self) -> bool:
        if self.device_id is None:
            return False
        ws_base = self._cfg.server.ws_url.rstrip("/")
        ws_url = f"{ws_base}/ws/v1/agent/{self.device_id}"

        # Pass credential as query param for WS authentication
        cred = self._cfg.device.credential
        if cred:
            ws_url += f"?token={cred}"

        try:
            self._ws = await websockets.connect(
                ws_url,
                ping_interval=20,
                ping_timeout=10,
                additional_headers=self._headers,
            )

            # Wait for auth_success message
            try:
                raw = await asyncio.wait_for(self._ws.recv(), timeout=5.0)
                msg = json.loads(raw)
                if msg.get("type") == "auth_success":
                    print(f"[Agent] WebSocket authenticated: device_id={msg.get('device_id')}")
                elif msg.get("type") == "error":
                    print(f"[Agent] WebSocket auth failed: {msg.get('message')}")
                    await self._ws.close()
                    self._ws = None
                    self.auth_rejected = True
                    return False
            except asyncio.TimeoutError:
                print("[Agent] WebSocket auth timeout — proceeding anyway")

            print(f"[Agent] WebSocket connected to {ws_base}/ws/v1/agent/{self.device_id}")
            return True
        except Exception as e:
            err_str = str(e)
            if "1008" in err_str or "403" in err_str:
                self.auth_rejected = True
                print(f"[Agent] WebSocket authentication rejected by server: {e}")
            else:
                print(f"[Agent] WebSocket connection failed: {e}")
            self._ws = None
            return False

    async def send_metrics(self, metrics: dict) -> bool:
        """Send telemetry via structured WebSocket message."""
        if self._ws is None:
            return False
        try:
            message = {
                "type": "telemetry",
                "timestamp": datetime.datetime.utcnow().isoformat(),
                "payload": metrics,
            }
            await self._ws.send(json.dumps(message))
            return True
        except Exception as e:
            print(f"[Agent] WebSocket send error: {e}")
            self._ws = None
            return False

    async def send_ws_heartbeat(self):
        """Send a structured heartbeat over WebSocket."""
        if self._ws is None:
            return
        try:
            message = {
                "type": "heartbeat",
                "timestamp": datetime.datetime.utcnow().isoformat(),
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:
            print(f"[Agent] WS heartbeat send error: {e}")

    async def send_command_result(self, command_id: int, status: str, output: str = ""):
        """Send command execution result back to server."""
        if self._ws is None:
            return
        try:
            message = {
                "type": "command_result",
                "command_id": command_id,
                "status": status,
                "output": output,
            }
            await self._ws.send(json.dumps(message))
        except Exception as e:
            print(f"[Agent] Command result send error: {e}")

    async def close_ws(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def check_incoming_commands(self) -> list[dict]:
        """Check for incoming server messages (commands, config updates, etc.)."""
        if not self.is_ws_connected or not self._ws:
            return []
        commands = []
        try:
            while True:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=0.05)
                data = json.loads(msg)
                msg_type = data.get("type", "")

                if msg_type == "command":
                    commands.append(data)
                elif msg_type == "config_update":
                    # Handle server-pushed config updates
                    if "metrics_interval" in data and data["metrics_interval"]:
                        new_interval = max(0.1, min(60.0, float(data["metrics_interval"])))
                        agent_settings.agent.metrics_interval = new_interval
                        print(f"[Agent] Metrics interval updated to {new_interval:.1f}s by server")
                elif msg_type in ("heartbeat_ack", "telemetry_ack"):
                    pass  # Acknowledgements — no action needed
                elif msg_type == "error":
                    print(f"[Agent] Server error: {data.get('message')}")
        except (asyncio.TimeoutError, Exception):
            pass
        return commands

    @property
    def is_ws_connected(self) -> bool:
        if self._ws is None:
            return False
        if hasattr(self._ws, "open"):
            return self._ws.open
        if hasattr(self._ws, "closed"):
            return not self._ws.closed
        return True
