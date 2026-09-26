"""Alert & Alert Rule Schemas."""
import re
import datetime
from typing import Optional, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_OPERATORS = {">", "<", "==", ">=", "<="}
_ALLOWED_SEVERITIES = {"info", "warning", "critical"}
_ALLOWED_ACTIONS = {"notification", "restart_service", "kill_process", "cleanup_temp"}
_KNOWN_METRICS = {
    "cpu_usage", "ram_usage_percent", "gpu_usage",
    "disk_read_speed", "disk_write_speed",
    "net_download_speed", "net_upload_speed",
    "disk_free_gb", "battery_percent",
}
_SAFE_TARGET_RE = re.compile(r"^[a-zA-Z0-9_.\- ]{1,128}$")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AlertOut(ORMBase):
    id: int
    device_id: int
    organization_id: int
    alert_type: str
    severity: str
    title: Optional[str] = None
    message: str
    status: str
    timestamp: datetime.datetime
    resolved_at: Optional[datetime.datetime] = None


class AlertRuleCreateRequest(BaseModel):
    device_id: Optional[int] = Field(default=None, gt=0)
    name: str = Field(..., min_length=1, max_length=255)
    metric_name: str
    operator: str
    threshold_value: float
    duration_seconds: int = Field(default=0, ge=0, le=86400)
    severity: str = "warning"
    action_type: str = "notification"
    action_target: Optional[str] = Field(default=None, max_length=128)
    enabled: bool = True

    @field_validator("operator")
    @classmethod
    def validate_operator(cls, v: str) -> str:
        if v not in _ALLOWED_OPERATORS:
            raise ValueError(f"Operator must be one of: {_ALLOWED_OPERATORS}")
        return v

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        v = v.lower()
        if v not in _ALLOWED_SEVERITIES:
            raise ValueError(f"Severity must be one of: {_ALLOWED_SEVERITIES}")
        return v

    @field_validator("metric_name")
    @classmethod
    def validate_metric_name(cls, v: str) -> str:
        if v not in _KNOWN_METRICS:
            raise ValueError(f"Unknown metric: {v}. Must be one of: {_KNOWN_METRICS}")
        return v

    @field_validator("action_type")
    @classmethod
    def validate_action_type(cls, v: str) -> str:
        if v not in _ALLOWED_ACTIONS:
            raise ValueError(f"Action type must be one of: {_ALLOWED_ACTIONS}")
        return v

    @field_validator("action_target")
    @classmethod
    def validate_action_target(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_TARGET_RE.match(v):
            raise ValueError("Action target contains invalid characters")
        return v


class AlertRuleOut(AlertRuleCreateRequest, ORMBase):
    id: int
    organization_id: int
    created_at: Optional[datetime.datetime] = None


class IncidentOut(ORMBase):
    id: int
    device_id: int
    organization_id: int
    rule_id: Optional[int] = None
    title: str
    severity: str
    status: str
    action_taken: Optional[str] = None
    log_output: Optional[str] = None
    triggered_at: datetime.datetime
    resolved_at: Optional[datetime.datetime] = None


class AuditLogOut(ORMBase):
    id: int
    timestamp: datetime.datetime
    actor_type: str
    actor_id: Optional[str] = None
    organization_id: Optional[int] = None
    action: str
    target_type: Optional[str] = None
    target_id: Optional[str] = None
    detail: Optional[str] = None
    ip_address: Optional[str] = None
    result: str


# ── AIOps Schemas ──

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
