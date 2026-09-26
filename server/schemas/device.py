"""Device Schemas."""
import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AssignedUserSummary(BaseModel):
    """Lightweight user info embedded in device responses."""
    id: int
    username: str
    full_name: Optional[str] = None
    email: str


class DeviceOut(ORMBase):
    id: int
    device_uuid: str
    hostname: str
    os_name: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: Optional[str] = None
    status: str = "pending"
    registered_at: Optional[datetime.datetime] = None
    last_seen: Optional[datetime.datetime] = None
    is_online: bool = False
    organization_id: int
    assigned_users: list[AssignedUserSummary] = []


class DeviceStatusOut(BaseModel):
    device_id: int
    is_online: bool
    status: str = "pending"
    last_seen: Optional[datetime.datetime] = None


class DeviceAssignmentCreateRequest(BaseModel):
    device_id: int
    user_id: int


class DeviceAssignmentOut(ORMBase):
    id: int
    device_id: int
    user_id: int
    assigned_by: Optional[int] = None
    assigned_at: Optional[datetime.datetime] = None
    device_hostname: Optional[str] = None
    username: Optional[str] = None
