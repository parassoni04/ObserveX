"""
ObserveX Agent — Application-Level Heartbeat.

Distinct from WebSocket ping/pong: this sends explicit heartbeat
payloads so the server can distinguish between a live agent and
a frozen process with an open TCP socket.
"""
import time
import asyncio
from agent.config import agent_settings
from agent.sender import AgentSender


class HeartbeatManager:
    """Manages periodic heartbeat sends and tracks heartbeat health."""

    def __init__(self, sender: AgentSender):
        self._sender = sender
        self._interval = agent_settings.agent.heartbeat_interval
        self._last_sent: float = 0.0
        self._last_success: float = 0.0
        self._consecutive_failures: int = 0

    @property
    def is_healthy(self) -> bool:
        """True if the last heartbeat succeeded or we haven't tried yet."""
        return self._consecutive_failures < 3

    @property
    def time_since_last_success(self) -> float:
        if self._last_success == 0.0:
            return 0.0
        return time.time() - self._last_success

    async def tick(self) -> bool:
        """Send a heartbeat if the interval has elapsed. Returns True if sent successfully."""
        now = time.time()
        if now - self._last_sent < self._interval:
            return True  # Not time yet, considered healthy

        self._last_sent = now
        try:
            await self._sender.send_heartbeat()
            self._last_success = now
            self._consecutive_failures = 0
            return True
        except Exception as e:
            self._consecutive_failures += 1
            print(f"[Heartbeat] Failed (attempt #{self._consecutive_failures}): {e}")
            return False
