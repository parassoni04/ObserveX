"""
Organization Model
==================

Represents a tenant/firm in the multi-tenant ObserveX platform.
Every organization is a logically isolated environment with its own
users, devices, enrollment codes, alerts, and monitoring data.

This is the root entity for tenant isolation — nearly every other
entity in the system carries an organization_id foreign key back
to this table.
"""
import datetime
from sqlalchemy import Column, Integer, String, DateTime
from sqlalchemy.orm import relationship
from server.models.base import Base


class Organization(Base):
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    slug = Column(String(100), unique=True, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="organization", cascade="all, delete-orphan")
    enrollment_codes = relationship("EnrollmentCode", back_populates="organization", cascade="all, delete-orphan")
    alert_rules = relationship("AlertRule", back_populates="organization", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Organization id={self.id} name={self.name!r}>"
