import datetime
from typing import Optional, Any
from pydantic import BaseModel, Field


# ── Device Schemas ──

class DeviceRegisterRequest(BaseModel):
    hostname: str
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    api_key: str


class DeviceRegisterResponse(BaseModel):
    device_id: int
    hostname: str
    status: str = "registered"


class DeviceOut(BaseModel):
    id: int
    hostname: str
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    registered_at: Optional[datetime.datetime] = None
    last_seen: Optional[datetime.datetime] = None
    is_online: bool = False

    class Config:
        from_attributes = True


class DeviceStatusOut(BaseModel):
    device_id: int
    is_online: bool
    last_seen: Optional[datetime.datetime] = None


# ── Static Info Schemas ──

class StaticInfoPayload(BaseModel):
    """Payload sent by the agent when uploading static hardware info."""
    computer_name: Optional[str] = None
    os_name: Optional[str] = None
    os_release: Optional[str] = None
    os_version: Optional[str] = None
    cpu_model: Optional[str] = None
    cpu_cores_physical: Optional[int] = None
    cpu_cores_logical: Optional[int] = None
    total_ram_gb: Optional[float] = None
    gpu_model: Optional[str] = None
    motherboard_mfg: Optional[str] = None
    motherboard_product: Optional[str] = None
    bios_name: Optional[str] = None
    bios_version: Optional[str] = None
    storage_devices: Optional[list] = None
    network_adapters: Optional[list] = None


class StaticInfoOut(StaticInfoPayload):
    device_id: int
    updated_at: Optional[datetime.datetime] = None

    class Config:
        from_attributes = True


# ── Metric Schemas ──

class MetricSnapshotOut(BaseModel):
    id: int
    device_id: int
    timestamp: datetime.datetime
    metrics: dict[str, Any]

    class Config:
        from_attributes = True


class MetricHistoryResponse(BaseModel):
    device_id: int
    count: int
    snapshots: list[MetricSnapshotOut]


class MetricSummaryResponse(BaseModel):
    device_id: int
    period_minutes: int
    avg_cpu: Optional[float] = None
    max_cpu: Optional[float] = None
    avg_ram: Optional[float] = None
    max_ram: Optional[float] = None
    avg_gpu: Optional[float] = None
    max_gpu: Optional[float] = None
    snapshot_count: int = 0


# ── Software Schemas ──

class SoftwareItem(BaseModel):
    name: str
    version: Optional[str] = None
    publisher: Optional[str] = None
    install_date: Optional[str] = None


class SoftwarePayload(BaseModel):
    software: list[SoftwareItem]


# ── Agent Heartbeat ──

class HeartbeatRequest(BaseModel):
    device_id: int
    api_key: str


class HeartbeatResponse(BaseModel):
    status: str = "ok"


# ── Event Logs ──

class EventLogItem(BaseModel):
    log_type: str
    timestamp: str
    source: str
    event_id: int
    severity: str
    message: str


class EventLogPayload(BaseModel):
    events: list[EventLogItem]


# ── WebSocket Messages ──

class WSSubscribe(BaseModel):
    action: str = "subscribe"       # subscribe / unsubscribe / set_interval
    device_id: Optional[int] = None
    value: Optional[float] = None   # for set_interval
