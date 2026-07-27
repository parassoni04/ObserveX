import asyncio
import datetime
import json
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect
import server.database as db
from server.models import MetricSnapshot


class ConnectionManager:
    """Manages agent and dashboard WebSocket connections and broadcasts metrics."""

    def __init__(self):
        # Agent connections: device_id -> WebSocket
        self.agent_connections: dict[int, WebSocket] = {}

        # Dashboard connections: WebSocket -> set of subscribed device_ids
        self.dashboard_connections: dict[WebSocket, set[int]] = {}

        # Latest metrics cache per device (in-memory for instant access)
        self.latest_metrics: dict[int, dict[str, Any]] = {}

        # Process list cache per device (in-memory, not persisted)
        self.device_processes: dict[int, list] = {}

        # Event log cache per device (in-memory, not persisted)
        self.device_events: dict[int, list] = {}

        # Lock for DB writes to avoid overwhelming the database
        self._db_write_lock = asyncio.Lock()

        # Counter to throttle DB writes (store every Nth snapshot)
        self._snapshot_counters: dict[int, int] = {}
        self.db_write_interval = 5  # Store 1 out of every 5 snapshots

    # ── Agent connections ──

    async def connect_agent(self, device_id: int, websocket: WebSocket):
        await websocket.accept()
        self.agent_connections[device_id] = websocket

    def disconnect_agent(self, device_id: int):
        self.agent_connections.pop(device_id, None)

    async def receive_agent_metrics(self, device_id: int, data: dict):
        """Process incoming metrics from an agent."""
        # Update in-memory cache
        self.latest_metrics[device_id] = data

        # Check if this data includes process list (sent separately)
        if "processes" in data:
            self.device_processes[device_id] = data.pop("processes")

        # Throttled DB write
        counter = self._snapshot_counters.get(device_id, 0) + 1
        self._snapshot_counters[device_id] = counter

        if counter >= self.db_write_interval:
            self._snapshot_counters[device_id] = 0
            # Store snapshot in background to avoid blocking the WS loop
            asyncio.create_task(self._store_snapshot(device_id, data))

        # Broadcast to subscribed dashboard clients
        await self._broadcast_to_dashboards(device_id, data)

    async def _store_snapshot(self, device_id: int, metrics: dict):
        """Persist a metric snapshot to database."""
        try:
            async with self._db_write_lock:
                async with db.async_session_factory() as session:
                    snapshot = MetricSnapshot(
                        device_id=device_id,
                        timestamp=datetime.datetime.utcnow(),
                        metrics=metrics,
                    )
                    session.add(snapshot)
                    await session.commit()
        except Exception as e:
            print(f"[WS Hub] Error storing snapshot for device {device_id}: {e}")

    # ── Dashboard connections ──

    async def connect_dashboard(self, websocket: WebSocket):
        await websocket.accept()
        self.dashboard_connections[websocket] = set()

    def disconnect_dashboard(self, websocket: WebSocket):
        self.dashboard_connections.pop(websocket, None)

    def subscribe_dashboard(self, websocket: WebSocket, device_id: int):
        if websocket in self.dashboard_connections:
            self.dashboard_connections[websocket].add(device_id)

    def unsubscribe_dashboard(self, websocket: WebSocket, device_id: int):
        if websocket in self.dashboard_connections:
            self.dashboard_connections[websocket].discard(device_id)

    async def _broadcast_to_dashboards(self, device_id: int, data: dict):
        """Send metrics to all dashboard clients subscribed to this device."""
        message = {
            "type": "metrics",
            "device_id": device_id,
            "data": data,
        }
        dead = []
        for ws, subscribed_ids in self.dashboard_connections.items():
            if device_id in subscribed_ids:
                try:
                    await ws.send_json(message)
                except Exception:
                    dead.append(ws)

        for ws in dead:
            self.disconnect_dashboard(ws)

    def get_online_device_ids(self) -> list[int]:
        return list(self.agent_connections.keys())

    async def send_agent_command(self, device_id: int, payload: dict) -> bool:
        """Send an action command to a connected agent over WebSocket."""
        ws = self.agent_connections.get(device_id)
        if not ws:
            return False
        try:
            await ws.send_json(payload)
            return True
        except Exception as e:
            print(f"[WS Hub] Failed to send command to agent {device_id}: {e}")
            return False


# Global singleton
connection_manager = ConnectionManager()
