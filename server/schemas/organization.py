"""Organization Schemas."""
import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class OrganizationOut(ORMBase):
    id: int
    name: str
    slug: Optional[str] = None
    created_at: Optional[datetime.datetime] = None


class OrgOverviewResponse(BaseModel):
    organization_name: str
    total_users: int
    total_devices: int
    online_devices: int
    offline_devices: int
    admin_count: int
    avg_health_score: float
