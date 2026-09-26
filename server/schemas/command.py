"""Command Schemas."""
import re
import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator

_ALLOWED_ACTIONS = {"restart_service", "kill_process", "cleanup_temp"}
_SAFE_TARGET_RE = re.compile(r"^[a-zA-Z0-9_.\- ]{1,128}$")


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CommandDispatchRequest(BaseModel):
    """Admin dispatches a command to a device."""
    device_id: int = Field(..., gt=0)
    command_type: str
    target: Optional[str] = Field(default=None, max_length=128)

    @field_validator("command_type")
    @classmethod
    def validate_command_type(cls, v: str) -> str:
        if v not in _ALLOWED_ACTIONS:
            raise ValueError(f"Command type must be one of: {_ALLOWED_ACTIONS}")
        return v

    @field_validator("target")
    @classmethod
    def validate_target(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _SAFE_TARGET_RE.match(v):
            raise ValueError("Target contains invalid characters")
        return v


class CommandLogOut(ORMBase):
    id: int
    organization_id: int
    device_id: int
    requested_by: Optional[int] = None
    command_type: str
    target: Optional[str] = None
    status: str
    result_output: Optional[str] = None
    created_at: datetime.datetime
    completed_at: Optional[datetime.datetime] = None
