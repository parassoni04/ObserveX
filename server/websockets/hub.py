"""
ObserveX Server — WebSocket Connection Manager.

Manages agent and dashboard WebSocket connections:
  - Agent connections: indexed by device_id
  - Dashboard connections: indexed by WebSocket with user_id and subscriptions
  - Metric broadcast: agent → subscribed dashboards
  - DB snapshot batching: every N metrics
"""
import asyncio
import datetime
from typing import Any, Optional
from fastapi import WebSocket
import server.database as db
from server.models import MetricSnapshot


class ConnectionManager:
    """Manages agent and dashboard WebSocket connections and broadcasts metrics."""

    def __init__(self):
        self.agent_connections: dict[int, WebSocket] = {}
        # Dashboard connections: ws → {"user_id": int|None, "subscriptions": set[int]}
        self.dashboard_connections: dict[WebSocket, dict[str, Any]] = {}
        self.latest_metrics: dict[int, dict[str, Any]] = {}
        self.device_processes: dict[int, list] = {}
        self.device_events: dict[int, list] = {}
        self._db_write_lock = asyncio.Lock()
        self._snapshot_counters: dict[int, int] = {}
        self.db_write_interval = 5

    async def connect_agent(self, device_id: int, websocket: WebSocket):
        await websocket.accept()
        self.agent_connections[device_id] = websocket

    def disconnect_agent(self, device_id: int):
        self.agent_connections.pop(device_id, None)

    async def receive_agent_metrics(self, device_id: int, data: dict):
        self.latest_metrics[device_id] = data
        if "processes" in data:
            self.device_processes[device_id] = data.pop("processes")

        counter = self._snapshot_counters.get(device_id, 0) + 1
        self._snapshot_counters[device_id] = counter
        if counter >= self.db_write_interval:
            self._snapshot_counters[device_id] = 0
            asyncio.create_task(self._store_snapshot(device_id, data))

        await self._broadcast_to_dashboards(device_id, data)

    async def _store_snapshot(self, device_id: int, metrics: dict):
        try:
            async with self._db_write_lock:
                async with db.async_session_factory() as session:
                    session.add(MetricSnapshot(device_id=device_id, timestamp=datetime.datetime.utcnow(), metrics=metrics))
                    await session.commit()
        except Exception as e:
            print(f"[WS Hub] Error storing snapshot for device {device_id}: {e}")

    async def connect_dashboard(self, websocket: WebSocket, user_id: Optional[int] = None):
        await websocket.accept()
        self.dashboard_connections[websocket] = {
            "user_id": user_id,
            "subscriptions": set(),
        }

    def disconnect_dashboard(self, websocket: WebSocket):
        self.dashboard_connections.pop(websocket, None)

    def subscribe_dashboard(self, websocket: WebSocket, device_id: int):
        if websocket in self.dashboard_connections:
            self.dashboard_connections[websocket]["subscriptions"].add(device_id)

    def unsubscribe_dashboard(self, websocket: WebSocket, device_id: int):
        if websocket in self.dashboard_connections:
            self.dashboard_connections[websocket]["subscriptions"].discard(device_id)

    async def _broadcast_to_dashboards(self, device_id: int, data: dict):
        message = {"type": "metrics", "device_id": device_id, "data": data}
        dead = []
        for ws, info in self.dashboard_connections.items():
            if device_id in info["subscriptions"]:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)
        for ws in dead:
            self.disconnect_dashboard(ws)

    def get_online_device_ids(self) -> list[int]:
        return list(self.agent_connections.keys())

    async def send_agent_command(self, device_id: int, payload: dict) -> bool:
        ws = self.agent_connections.get(device_id)
        if not ws:
            return False
        try:
            await ws.send_json(payload)
            return True
        except Exception as e:
            print(f"[WS Hub] Failed to send command to agent {device_id}: {e}")
            return False


connection_manager = ConnectionManager()
