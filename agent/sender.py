import asyncio
import json
import httpx
import websockets
from typing import Optional, Any
from agent.config import agent_settings


class AgentSender:
    """Handles HTTP REST and WebSocket communication with the ObserveX server."""

    def __init__(self):
        self.server_url = agent_settings.OBSERVEX_SERVER_URL
        self.api_key = agent_settings.OBSERVEX_API_KEY
        self.device_id: Optional[int] = None
        self._ws: Optional[Any] = None

    async def _post(self, path: str, payload: dict, params: dict | None = None, timeout: float = 10.0):
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(f"{self.server_url}{path}", json=payload, params=params)
            resp.raise_for_status()
            return resp.json()

    async def register(self, hostname: str, os_name: str, os_version: str) -> int:
        data = await self._post("/api/v1/agent/register", {"hostname": hostname, "os_name": os_name, "os_version": os_version, "api_key": self.api_key})
        self.device_id = data["device_id"]
        print(f"[Agent] Registered as device_id={self.device_id} ({data['status']})")
        return self.device_id

    async def send_heartbeat(self):
        if self.device_id is None:
            return
        await self._post("/api/v1/agent/heartbeat", {"device_id": self.device_id, "api_key": self.api_key}, timeout=5.0)

    async def send_static_info(self, info: dict):
        if self.device_id is None:
            return
        await self._post("/api/v1/agent/static-info", info, params={"device_id": self.device_id, "api_key": self.api_key}, timeout=15.0)
        print(f"[Agent] Static info uploaded for device_id={self.device_id}")

    async def send_software_list(self, software: list[dict]):
        if self.device_id is None:
            return
        await self._post("/api/v1/agent/software", {"software": software}, params={"device_id": self.device_id, "api_key": self.api_key}, timeout=30.0)
        print(f"[Agent] Software list uploaded ({len(software)} items)")

    async def send_event_logs(self, events: list[dict]):
        if self.device_id is None:
            return
        await self._post("/api/v1/agent/events", {"events": events}, params={"device_id": self.device_id, "api_key": self.api_key}, timeout=30.0)
        print(f"[Agent] Event logs uploaded ({len(events)} events)")

    # ── WebSocket Methods ──

    async def connect_ws(self) -> bool:
        if self.device_id is None:
            return False
        ws_url = f"{agent_settings.ws_url}/ws/v1/agent/{self.device_id}"
        try:
            self._ws = await websockets.connect(ws_url, ping_interval=20, ping_timeout=10)
            print(f"[Agent] WebSocket connected to {ws_url}")
            return True
        except Exception as e:
            print(f"[Agent] WebSocket connection failed: {e}")
            self._ws = None
            return False

    async def send_metrics(self, metrics: dict):
        if self._ws is None:
            return False
        try:
            await self._ws.send(json.dumps(metrics))
            return True
        except Exception as e:
            print(f"[Agent] WebSocket send error: {e}")
            self._ws = None
            return False

    async def close_ws(self):
        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

    async def check_incoming_commands(self) -> list[dict]:
        if not self.is_ws_connected or not self._ws:
            return []
        commands = []
        try:
            while True:
                msg = await asyncio.wait_for(self._ws.recv(), timeout=0.05)
                data = json.loads(msg)
                if isinstance(data, dict) and data.get("type") == "command":
                    commands.append(data)
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
