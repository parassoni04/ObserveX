"""
User Model
==========

Represents a human user of the ObserveX platform — either an organization
administrator or a regular employee.

Key design decisions:
- Every user belongs to exactly one organization (non-nullable FK after
  the "create environment" flow).
- Role is a simple string enum ("admin" / "user") rather than a full
  RBAC table, matching the two-tier permission model specified in the
  requirements.
- Password is stored as a bcrypt hash; never plaintext.
- Device access is managed through the DeviceUserAssignment association
  table, not a direct FK on Device.
"""
import datetime
from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey
from sqlalchemy.orm import relationship
from server.models.base import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)  # "admin" or "user"
    is_active = Column(Boolean, default=True, nullable=False)
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="users")
    device_assignments = relationship(
        "DeviceUserAssignment",
        back_populates="user",
        foreign_keys="DeviceUserAssignment.user_id",
        cascade="all, delete-orphan",
    )

    def __repr__(self):
        return f"<User id={self.id} username={self.username!r} role={self.role}>"
