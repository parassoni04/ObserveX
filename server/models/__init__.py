"""
ObserveX Server — Model Registry.

Re-exports all ORM models and the Base class so that other modules
can import from a single location:

    from server.models import Base, User, Device, Organization, ...

The import order matters: Base must be imported before any model
that inherits from it, and all models must be imported before
Base.metadata.create_all() is called so that SQLAlchemy discovers
all tables.
"""
from server.models.base import Base

from server.models.organization import Organization
from server.models.user import User
from server.models.device import Device, DeviceUserAssignment
from server.models.enrollment import EnrollmentCode
from server.models.telemetry import DeviceStaticInfo, MetricSnapshot
from server.models.alert import Alert, AlertRule
from server.models.incident import Incident
from server.models.software import DeviceSoftware
from server.models.windows_event import WindowsEvent
from server.models.command import CommandLog
from server.models.audit import AuditLog

__all__ = [
    "Base",
    "Organization",
    "User",
    "Device",
    "DeviceUserAssignment",
    "EnrollmentCode",
    "DeviceStaticInfo",
    "MetricSnapshot",
    "Alert",
    "AlertRule",
    "Incident",
    "DeviceSoftware",
    "WindowsEvent",
    "CommandLog",
    "AuditLog",
]
