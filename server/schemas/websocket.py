"""
WebSocket Protocol Schemas
==========================

Defines the structured message types for the ObserveX WebSocket protocol.
Both the server and agent use these message types for communication.

Every message has a "type" field that identifies the message kind.
This replaces the old implicit protocol where raw metric dicts
were sent without any envelope or type identification.
"""
from typing import Optional, Any
from pydantic import BaseModel


# ── Server → Agent Messages ──

class WSAuthSuccess(BaseModel):
    type: str = "auth_success"
    device_id: int
    organization_id: int
    organization_name: str
    config: dict = {}  # Server-pushed config (metrics_interval, etc.)


class WSHeartbeatAck(BaseModel):
    type: str = "heartbeat_ack"
    timestamp: str


class WSTelemetryAck(BaseModel):
    type: str = "telemetry_ack"


class WSCommand(BaseModel):
    type: str = "command"
    command_id: int
    action: str
    target: Optional[str] = None
    timestamp: str


class WSAlertNotification(BaseModel):
    type: str = "alert"
    alert_id: int
    severity: str
    title: str
    message: str
    device_id: int
    timestamp: str


class WSConfigUpdate(BaseModel):
    type: str = "config_update"
    metrics_interval: Optional[float] = None
    heartbeat_interval: Optional[float] = None


class WSError(BaseModel):
    type: str = "error"
    message: str
    code: Optional[str] = None


# ── Agent → Server Messages ──

class WSHeartbeat(BaseModel):
    type: str = "heartbeat"
    timestamp: str


class WSTelemetry(BaseModel):
    type: str = "telemetry"
    timestamp: str
    payload: dict[str, Any]


class WSCommandResult(BaseModel):
    type: str = "command_result"
    command_id: int
    status: str  # success, failed
    output: Optional[str] = None


# ── Dashboard Messages ──

class WSDashboardSubscribe(BaseModel):
    action: str = "subscribe"
    device_id: int


class WSDashboardUnsubscribe(BaseModel):
    action: str = "unsubscribe"
    device_id: int
