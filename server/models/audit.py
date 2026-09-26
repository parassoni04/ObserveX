"""
Audit Log Model
===============

Immutable audit log entries recording security-relevant events across
the ObserveX platform: logins, enrollment, device access, commands,
credential changes, etc.

Design principles:
- Append-only: audit logs are never updated or deleted.
- Fire-and-forget: writing an audit log must never crash the application.
- organization_id allows tenant-scoped audit queries.
- actor_type distinguishes between "user", "agent", and "system" actions.
- result distinguishes between "success", "denied", and "error" outcomes.
"""
import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, Index
from server.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    actor_type = Column(String(20), nullable=False)    # "user", "agent", "system"
    actor_id = Column(String(100), nullable=True)      # user_id or device_id as string
    organization_id = Column(Integer, nullable=True)   # Nullable for system-level events
    action = Column(String(100), nullable=False, index=True)
    target_type = Column(String(50), nullable=True)    # "device", "user", "enrollment_code"
    target_id = Column(String(100), nullable=True)
    detail = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    result = Column(String(20), nullable=False, default="success")  # success, denied, error

    __table_args__ = (
        Index("ix_audit_ts_action", "timestamp", "action"),
        Index("ix_audit_actor", "actor_type", "actor_id"),
        Index("ix_audit_org", "organization_id"),
    )

    def __repr__(self):
        return f"<AuditLog id={self.id} action={self.action!r} result={self.result}>"
