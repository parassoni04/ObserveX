"""Telemetry Schemas."""
import datetime
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class StaticInfoPayload(BaseModel):
    """Hardware/OS info uploaded by agent."""
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


class StaticInfoOut(StaticInfoPayload, ORMBase):
    device_id: int
    updated_at: Optional[datetime.datetime] = None


class MetricSnapshotOut(ORMBase):
    id: int
    device_id: int
    timestamp: datetime.datetime
    metrics: dict[str, Any]


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


class SoftwareItem(BaseModel):
    name: str
    version: Optional[str] = None
    publisher: Optional[str] = None
    install_date: Optional[str] = None


class SoftwarePayload(BaseModel):
    software: list[SoftwareItem]


class EventLogItem(BaseModel):
    log_type: str
    timestamp: str
    source: str
    event_id: int
    severity: str
    message: str


class EventLogPayload(BaseModel):
    events: list[EventLogItem]


class HeartbeatRequest(BaseModel):
    device_id: int


class HeartbeatResponse(BaseModel):
    status: str = "ok"
