"""
Command Log Model
=================

Records every command dispatched from the server to an agent, providing
a complete audit trail of remote operations.

Security design:
- Every command has a type from an explicit allowlist (no arbitrary shell).
- The requesting user, target device, and organization are all recorded.
- Command status tracks the full lifecycle: pending → sent → success → failed.
- Results from the agent are recorded in result_output.

This model replaces the old system where commands were fire-and-forget
with no persistence or audit trail.
"""
import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.models.base import Base


class CommandLog(Base):
    __tablename__ = "command_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False,
    )
    requested_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    command_type = Column(String(50), nullable=False)   # From allowlist
    target = Column(String(255), nullable=True)         # e.g., service name, process name
    status = Column(String(20), default="pending", nullable=False)  # pending, sent, success, failed
    result_output = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="command_logs")
    requester = relationship("User")

    __table_args__ = (
        Index("ix_command_logs_device", "device_id"),
        Index("ix_command_logs_org", "organization_id"),
    )

    def __repr__(self):
        return f"<CommandLog id={self.id} type={self.command_type!r} status={self.status}>"
