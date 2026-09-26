"""
Incident Model
==============

Represents a tracked incident created when an alert rule is triggered.
Incidents have a lifecycle: open → acknowledged → auto_remediated → resolved.

Design:
- organization_id is now required (was missing in old schema).
- action_taken and log_output record what remediation was attempted
  and the result, providing a complete audit trail.
"""
import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.models.base import Base


class Incident(Base):
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    rule_id = Column(
        Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True,
    )
    title = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False)
    status = Column(String(30), default="open")  # open, acknowledged, auto_remediated, resolved
    action_taken = Column(String(100), nullable=True)
    log_output = Column(Text, nullable=True)
    triggered_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    device = relationship("Device", back_populates="incidents")

    __table_args__ = (
        Index("ix_incidents_org_status", "organization_id", "status"),
        Index("ix_incidents_device_ts", "device_id", "triggered_at"),
    )

    def __repr__(self):
        return f"<Incident id={self.id} severity={self.severity} status={self.status}>"
