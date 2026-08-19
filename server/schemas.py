import datetime
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


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


class DeviceOut(ORMBase):
    id: int
    hostname: str
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    registered_at: Optional[datetime.datetime] = None
    last_seen: Optional[datetime.datetime] = None
    is_online: bool = False
    organization_id: Optional[int] = None
    assigned_user_id: Optional[int] = None


# ── Auth & User Schemas ──

class UserRegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: Optional[str] = None


class UserLoginRequest(BaseModel):
    username_or_email: str
    password: str


class UserOut(ORMBase):
    id: int
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    organization_id: Optional[int] = None
    created_at: Optional[datetime.datetime] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreateAdmin(BaseModel):
    email: str
    username: str
    password: str
    full_name: Optional[str] = None
    role: str = "user"
    organization_id: Optional[int] = None


class UserUpdateAdmin(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None
    organization_id: Optional[int] = None


class OrganizationOut(ORMBase):
    id: int
    name: str
    created_at: Optional[datetime.datetime] = None


class DeviceAssignRequest(BaseModel):
    assigned_user_id: Optional[int] = None
    organization_id: Optional[int] = None


class OrgOverviewResponse(BaseModel):
    organization_name: str
    total_users: int
    total_devices: int
    online_devices: int
    offline_devices: int
    admin_count: int
    avg_health_score: float


class DeviceStatusOut(BaseModel):
    device_id: int
    is_online: bool
    last_seen: Optional[datetime.datetime] = None


# ── Static Info Schemas ──

class StaticInfoPayload(BaseModel):
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


# ── Metric Schemas ──

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
    action: str = "subscribe"
    device_id: Optional[int] = None
    value: Optional[float] = None


# ── Alert Schemas ──

class AlertCreateRequest(BaseModel):
    device_id: int
    alert_type: str
    severity: str
    message: str


class AlertOut(ORMBase):
    id: int
    device_id: int
    alert_type: str
    severity: str
    message: str
    timestamp: datetime.datetime


# ── Analytics & Correlation Schemas ──

class TrendSummaryResponse(BaseModel):
    device_id: int
    period: str
    snapshot_count: int
    cpu_avg: float
    cpu_min: float
    cpu_max: float
    cpu_trend_slope: float
    ram_avg: float
    ram_min: float
    ram_max: float
    disk_read_max: float
    disk_write_max: float
    net_download_max: float
    net_upload_max: float


class LogCorrelationResponse(BaseModel):
    device_id: int
    target_timestamp: str
    window_minutes: int
    metrics_at_timestamp: Optional[dict[str, Any]] = None
    events: list[dict[str, Any]] = []
    processes: list[dict[str, Any]] = []
    alerts: list[AlertOut] = []


# ── Automation & Intelligent Alerting Schemas ──

class AlertRuleCreateRequest(BaseModel):
    device_id: Optional[int] = None
    name: str
    metric_name: str
    operator: str
    threshold_value: float
    duration_seconds: int = 0
    severity: str = "warning"
    action_type: str = "notification"
    action_target: Optional[str] = None
    enabled: bool = True


class AlertRuleOut(AlertRuleCreateRequest, ORMBase):
    id: int
    created_at: Optional[datetime.datetime] = None


class IncidentOut(ORMBase):
    id: int
    device_id: int
    rule_id: Optional[int] = None
    title: str
    severity: str
    status: str
    action_taken: Optional[str] = None
    log_output: Optional[str] = None
    triggered_at: datetime.datetime
    resolved_at: Optional[datetime.datetime] = None


class ActionDispatchPayload(BaseModel):
    device_id: int
    action_type: str
    target: Optional[str] = None


class MaintenanceTaskOut(ORMBase):
    id: int
    device_id: Optional[int] = None
    title: str
    task_type: str
    frequency: str
    last_run: Optional[datetime.datetime] = None
    next_run: Optional[datetime.datetime] = None
    enabled: bool


# ── AIOps & Machine Learning Schemas ──

class AnomalyItem(BaseModel):
    timestamp: Optional[str] = None
    metric_name: str
    metric_label: str
    value: float
    baseline_mean: float
    z_score: float
    priority_score: float
    severity: str
    reason: str


class FailureForecastWarning(BaseModel):
    resource: str
    severity: str
    current_value: str
    estimated_ttf: str
    recommendation: str


class FailureForecastResponse(BaseModel):
    has_critical_failure_risk: bool
    risk_level: str
    warnings: list[FailureForecastWarning]


class RootCauseSuggestionItem(BaseModel):
    anomaly_metric: str
    trigger_value: str
    root_cause_type: str
    suspect: str
    suspect_detail: str
    suggested_action: Optional[str] = None
    suggested_target: Optional[str] = None
    reasoning: str


class AIOpsHealthInsightsResponse(BaseModel):
    risk_level: str
    anomaly_count: int
    summary: str
    action_item: str
    health_score: int
    generated_at: str
