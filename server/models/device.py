"""
Device Model & Device-User Assignment
======================================

Represents a monitored Windows device enrolled in the ObserveX platform,
plus the many-to-many association between devices and users.

Key design decisions:
- Every device belongs to exactly one organization (non-nullable FK),
  enforced at enrollment time via the enrollment code's org association.
- Device credentials are ONLY stored as bcrypt hashes (api_key_hash).
  The legacy plaintext api_key column is removed entirely.
- The legacy assigned_user_id single-FK pattern is removed; all
  device↔user assignments go through DeviceUserAssignment.
- device_uuid is a UUID4 string generated at enrollment, used by the
  agent for persistent identity across restarts.
- Status follows a state machine: pending → active → stale → offline → revoked.
"""
import datetime
import uuid
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey,
    Index, UniqueConstraint,
)
from sqlalchemy.orm import relationship
from server.models.base import Base


class Device(Base):
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_uuid = Column(
        String(36), unique=True, index=True, nullable=False,
        default=lambda: str(uuid.uuid4()),
    )
    hostname = Column(String(255), nullable=False)
    os_name = Column(String(100), nullable=True)
    os_version = Column(String(100), nullable=True)
    agent_version = Column(String(50), nullable=True)

    # Credential: bcrypt hash of the device API key (plaintext never stored)
    api_key_hash = Column(String(255), nullable=False)

    # Device lifecycle state: pending, active, stale, offline, revoked
    status = Column(String(20), default="pending", nullable=False)
    registered_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow)
    is_online = Column(Boolean, default=False)

    # Tenant ownership — every device belongs to exactly one org
    organization_id = Column(
        Integer,
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Relationships
    organization = relationship("Organization", back_populates="devices")
    static_info = relationship(
        "DeviceStaticInfo", back_populates="device",
        uselist=False, cascade="all, delete-orphan",
    )
    metric_snapshots = relationship(
        "MetricSnapshot", back_populates="device", cascade="all, delete-orphan",
    )
    alerts = relationship("Alert", back_populates="device", cascade="all, delete-orphan")
    software = relationship("DeviceSoftware", back_populates="device", cascade="all, delete-orphan")
    windows_events = relationship("WindowsEvent", back_populates="device", cascade="all, delete-orphan")
    command_logs = relationship("CommandLog", back_populates="device", cascade="all, delete-orphan")
    user_assignments = relationship(
        "DeviceUserAssignment", back_populates="device", cascade="all, delete-orphan",
    )
    incidents = relationship("Incident", back_populates="device", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Device id={self.id} hostname={self.hostname!r} status={self.status}>"


class DeviceUserAssignment(Base):
    """
    Many-to-many association between devices and users.

    Tracks which users have access to which devices. Only admins can
    create/delete assignments. The assigned_by field records who made
    the assignment for audit purposes.
    """
    __tablename__ = "device_user_assignments"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    assigned_by = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    assigned_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    device = relationship("Device", back_populates="user_assignments")
    user = relationship("User", back_populates="device_assignments", foreign_keys=[user_id])
    assigner = relationship("User", foreign_keys=[assigned_by])

    __table_args__ = (
        UniqueConstraint("device_id", "user_id", name="uq_device_user"),
        Index("ix_dua_device", "device_id"),
        Index("ix_dua_user", "user_id"),
    )

    def __repr__(self):
        return f"<DeviceUserAssignment device={self.device_id} user={self.user_id}>"
