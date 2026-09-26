"""
WebSocket Connection Manager
=============================

Central hub for all WebSocket connections — both agents and dashboards.
Tracks connections by device_id (agents) and by subscription (dashboards).

Key design differences from the old architecture:
1. Structured message types (not raw dicts)
2. Per-agent heartbeat tracking with timeout detection
3. Organization-scoped dashboard broadcasts
4. Latest metrics stored per device for immediate dashboard delivery
5. Thread-safe connection tracking

This module is the single source of truth for:
- Which agents are currently connected
- Which dashboards are subscribed to which devices
- The latest telemetry for each device (in-memory cache)
- In-memory event log cache per device
"""
import asyncio
import datetime
import json
from typing import Optional, Any
from fastapi import WebSocket
from server.logging import get_logger

logger = get_logger("ws_manager")


class _AgentConnection:
    """Tracks state for a single connected agent."""

    def __init__(self, ws: WebSocket, device_id: int, organization_id: int):
        self.ws = ws
        self.device_id = device_id
        self.organization_id = organization_id
        self.connected_at = datetime.datetime.utcnow()
        self.last_heartbeat = datetime.datetime.utcnow()

    def touch_heartbeat(self):
        self.last_heartbeat = datetime.datetime.utcnow()


class _DashboardConnection:
    """Tracks state for a connected dashboard client."""

    def __init__(self, ws: WebSocket, user_id: int, organization_id: int):
        self.ws = ws
        self.user_id = user_id
        self.organization_id = organization_id
        self.subscribed_devices: set[int] = set()


class ConnectionManager:
    """
    Central WebSocket connection manager.

    Maintains separate registries for agent connections and
    dashboard connections. Provides methods for sending commands
    to specific agents and broadcasting telemetry to dashboards.
    """

    def __init__(self):
        # Agent connections: device_id → _AgentConnection
        self._agents: dict[int, _AgentConnection] = {}

        # Dashboard connections: WebSocket → _DashboardConnection
        self._dashboards: dict[WebSocket, _DashboardConnection] = {}

        # In-memory telemetry cache: device_id → latest metrics dict
        self.latest_metrics: dict[int, dict[str, Any]] = {}

        # In-memory process list cache: device_id → [process_dict]
        self.latest_processes: dict[int, list[dict]] = {}

        # In-memory Windows event cache: device_id → [event_dict]
        self.device_events: dict[int, list[dict]] = {}

        # Metric history ring buffer: device_id → [snapshot_dict]
        self.metric_history: dict[int, list[dict]] = {}
        self._max_history = 300  # ~5 min at 1s interval

    # ── Agent Management ──

    def register_agent(self, ws: WebSocket, device_id: int, organization_id: int):
        """Register a newly authenticated agent connection."""
        self._agents[device_id] = _AgentConnection(ws, device_id, organization_id)
        logger.info("Agent connected: device_id=%s org_id=%s", device_id, organization_id)

    def unregister_agent(self, device_id: int):
        """Remove an agent connection."""
        if device_id in self._agents:
            del self._agents[device_id]
            logger.info("Agent disconnected: device_id=%s", device_id)

    def get_agent(self, device_id: int) -> Optional[_AgentConnection]:
        """Get an agent connection by device_id."""
        return self._agents.get(device_id)

    def is_agent_online(self, device_id: int) -> bool:
        return device_id in self._agents

    def get_online_device_ids(self) -> list[int]:
        return list(self._agents.keys())

    def get_online_device_ids_for_org(self, organization_id: int) -> list[int]:
        return [
            conn.device_id for conn in self._agents.values()
            if conn.organization_id == organization_id
        ]

    def touch_agent_heartbeat(self, device_id: int):
        """Update the last heartbeat timestamp for an agent."""
        agent = self._agents.get(device_id)
        if agent:
            agent.touch_heartbeat()

    async def send_to_agent(self, device_id: int, message: dict) -> bool:
        """
        Send a JSON message to a specific agent.
        Returns True if sent successfully, False otherwise.
        """
        agent = self._agents.get(device_id)
        if not agent:
            return False
        try:
            await agent.ws.send_json(message)
            return True
        except Exception as e:
            logger.error("Failed to send to agent device_id=%s: %s", device_id, e)
            self.unregister_agent(device_id)
            return False

    # ── Dashboard Management ──

    def register_dashboard(self, ws: WebSocket, user_id: int, organization_id: int):
        """Register a newly authenticated dashboard connection."""
        self._dashboards[ws] = _DashboardConnection(ws, user_id, organization_id)
        logger.info("Dashboard connected: user_id=%s org_id=%s", user_id, organization_id)

    def unregister_dashboard(self, ws: WebSocket):
        """Remove a dashboard connection."""
        if ws in self._dashboards:
            del self._dashboards[ws]
            logger.info("Dashboard disconnected")

    def subscribe_dashboard(self, ws: WebSocket, device_id: int):
        """Subscribe a dashboard to a specific device's telemetry."""
        conn = self._dashboards.get(ws)
        if conn:
            conn.subscribed_devices.add(device_id)

    def unsubscribe_dashboard(self, ws: WebSocket, device_id: int):
        """Unsubscribe a dashboard from a device's telemetry."""
        conn = self._dashboards.get(ws)
        if conn:
            conn.subscribed_devices.discard(device_id)

    # ── Telemetry Processing ──

    @staticmethod
    def _normalize_metrics(m: dict) -> dict:
        """
        Ensure bidirectional alias compatibility between agent metric keys and frontend expectations.
        """
        # CPU
        if "cpu_usage" in m and "cpu_percent" not in m:
            m["cpu_percent"] = m["cpu_usage"]
        elif "cpu_percent" in m and "cpu_usage" not in m:
            m["cpu_usage"] = m["cpu_percent"]

        # RAM
        if "ram_usage_percent" in m and "ram_percent" not in m:
            m["ram_percent"] = m["ram_usage_percent"]
        elif "ram_percent" in m and "ram_usage_percent" not in m:
            m["ram_usage_percent"] = m["ram_percent"]

        # Disk
        if "disk_usage_percent" in m and "disk_percent" not in m:
            m["disk_percent"] = m["disk_usage_percent"]
        elif "disk_percent" in m and "disk_usage_percent" not in m:
            m["disk_usage_percent"] = m["disk_percent"]

        # GPU
        if "gpu_usage" in m and "gpu_percent" not in m:
            m["gpu_percent"] = m["gpu_usage"]
        elif "gpu_percent" in m and "gpu_usage" not in m:
            m["gpu_usage"] = m["gpu_percent"]

        # CPU Freq (e.g. "3.20 GHz" -> cpu_freq_mhz = 3200)
        if "cpu_frequency" in m and "cpu_freq_mhz" not in m:
            try:
                val = float(str(m["cpu_frequency"]).split()[0])
                m["cpu_freq_mhz"] = round(val * 1000 if "ghz" in str(m["cpu_frequency"]).lower() else val, 1)
            except Exception:
                pass

        # Network Speeds (bytes/sec <-> Mbps)
        if "net_upload_speed" in m and "net_sent_mbps" not in m:
            try:
                m["net_sent_mbps"] = round(float(m["net_upload_speed"]) * 8 / 1e6, 2)
            except Exception:
                pass
        if "net_download_speed" in m and "net_recv_mbps" not in m:
            try:
                m["net_recv_mbps"] = round(float(m["net_download_speed"]) * 8 / 1e6, 2)
            except Exception:
                pass

        # Disk Speeds (bytes/sec <-> MB/s)
        if "disk_read_speed" in m and "disk_read_mbps" not in m:
            try:
                m["disk_read_mbps"] = round(float(m["disk_read_speed"]) / (1024 * 1024), 2)
            except Exception:
                pass
        if "disk_write_speed" in m and "disk_write_mbps" not in m:
            try:
                m["disk_write_mbps"] = round(float(m["disk_write_speed"]) / (1024 * 1024), 2)
            except Exception:
                pass

        return m

    def update_metrics(self, device_id: int, metrics: dict):
        """Update the latest metrics cache for a device."""
        metrics = self._normalize_metrics(metrics)
        metrics["timestamp"] = datetime.datetime.utcnow().isoformat()
        self.latest_metrics[device_id] = metrics

        # Update ring buffer history
        if device_id not in self.metric_history:
            self.metric_history[device_id] = []
        self.metric_history[device_id].append({"timestamp": metrics["timestamp"], "metrics": metrics})
        if len(self.metric_history[device_id]) > self._max_history:
            self.metric_history[device_id] = self.metric_history[device_id][-self._max_history:]

    def update_processes(self, device_id: int, processes: list[dict]):
        """Update the latest process list cache for a device."""
        self.latest_processes[device_id] = processes

    # ── Broadcasting ──

    async def broadcast_to_dashboards(self, device_id: int, message: dict):
        """
        Send a message to all dashboards subscribed to a specific device.
        Only sends to dashboards in the same organization as the device.
        """
        agent = self._agents.get(device_id)
        org_id = agent.organization_id if agent else None

        dead_connections = []
        for ws, conn in self._dashboards.items():
            # Organization isolation: only send to dashboards in the same org
            if org_id and conn.organization_id != org_id:
                continue
            # Only send if dashboard is subscribed to this device (or any)
            if device_id not in conn.subscribed_devices and conn.subscribed_devices:
                continue
            try:
                await ws.send_json(message)
            except Exception:
                dead_connections.append(ws)

        for ws in dead_connections:
            self.unregister_dashboard(ws)

    async def broadcast_telemetry(self, device_id: int, metrics: dict):
        """Process incoming telemetry: cache it and broadcast to dashboards."""
        self.update_metrics(device_id, metrics)
        await self.broadcast_to_dashboards(device_id, {
            "type": "telemetry",
            "device_id": device_id,
            "timestamp": metrics.get("timestamp"),
            "payload": metrics,
        })

    async def broadcast_alert_to_dashboards(self, device_id: int, alert_data: dict):
        """Broadcast an alert to subscribed dashboards."""
        await self.broadcast_to_dashboards(device_id, {
            "type": "alert",
            **alert_data,
        })

    # ── Cleanup ──

    def cleanup_device(self, device_id: int):
        """Remove all cached data for a device."""
        self.latest_metrics.pop(device_id, None)
        self.latest_processes.pop(device_id, None)
        self.device_events.pop(device_id, None)
        self.metric_history.pop(device_id, None)

    def reset(self):
        """Clear all connections and cached data (testing & server reset)."""
        self._agents.clear()
        self._dashboards.clear()
        self.latest_metrics.clear()
        self.latest_processes.clear()
        self.device_events.clear()
        self.metric_history.clear()

    @property
    def stats(self) -> dict:
        """Connection statistics for monitoring."""
        return {
            "agents_connected": len(self._agents),
            "dashboards_connected": len(self._dashboards),
            "devices_with_metrics": len(self.latest_metrics),
        }


# Singleton instance used across the application
connection_manager = ConnectionManager()
