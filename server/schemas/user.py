"""User Schemas."""
import datetime
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ORMBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class UserRegisterRequest(BaseModel):
    email: str
    username: str
    password: str
    full_name: Optional[str] = None


class UserOut(ORMBase):
    id: int
    email: str
    username: str
    full_name: Optional[str] = None
    role: str
    is_active: bool
    organization_id: int
    created_at: Optional[datetime.datetime] = None


class UserCreateAdmin(BaseModel):
    """Admin creates a user within their organization."""
    email: str
    username: str
    password: str
    full_name: Optional[str] = None
    role: str = "user"


class UserUpdateAdmin(BaseModel):
    """Admin updates a user's role or active status."""
    role: Optional[str] = None
    is_active: Optional[bool] = None
