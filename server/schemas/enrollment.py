"""Enrollment Schemas."""
import re
import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class EnrollmentCodeCreateRequest(BaseModel):
    """Admin creates an enrollment code."""
    expires_in_hours: int = Field(default=24, ge=1, le=8760)  # Max 1 year
    max_uses: int = Field(default=1, ge=0)  # 0 = unlimited


class EnrollmentCodeOut(ORMBase):
    id: int
    code: str
    organization_id: int
    created_by_user_id: Optional[int] = None
    created_at: Optional[datetime.datetime] = None
    expires_at: datetime.datetime
    max_uses: int
    usage_count: int
    is_revoked: bool


class EnrollmentRequest(BaseModel):
    """Agent sends this to enroll with the server."""
    enrollment_code: str = Field(..., min_length=1, max_length=20)
    hostname: str = Field(..., min_length=1, max_length=255)
    os_name: Optional[str] = Field(default=None, max_length=100)
    os_version: Optional[str] = Field(default=None, max_length=100)

    @field_validator("enrollment_code")
    @classmethod
    def validate_enrollment_code(cls, v: str) -> str:
        v = v.strip().upper()
        if not re.match(r"^OX-[A-F0-9]{4}-[A-F0-9]{4}$", v):
            raise ValueError("Enrollment code must match format OX-XXXX-XXXX")
        return v

    @field_validator("hostname")
    @classmethod
    def validate_hostname(cls, v: str) -> str:
        v = v.strip()
        if re.search(r"[;&|`$\\/><\x00-\x1f]", v):
            raise ValueError("Hostname contains invalid characters")
        return v


class EnrollmentResponse(BaseModel):
    """Server returns this after successful enrollment."""
    device_id: int
    device_uuid: str
    api_key: str  # Returned ONCE — stored only as hash on server
    organization_name: str
    server_ws_url: str
    status: str = "enrolled"
