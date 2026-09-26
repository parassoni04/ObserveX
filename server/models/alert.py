"""
Alert & Alert Rule Models
=========================

Alert:     An individual alert event triggered for a specific device.
AlertRule: A configurable rule that evaluates live telemetry and creates
           alerts/incidents when thresholds are breached.

Security:
- AlertRule now carries organization_id so tenant isolation is enforced.
  The old schema had no org association on AlertRule, which meant rules
  from one tenant could theoretically evaluate devices from another.
- Alert severity is constrained to: info, warning, critical.
- Alert status tracks lifecycle: open, acknowledged, resolved.
"""
import datetime
from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.models.base import Base


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)  # info, warning, critical
    title = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    status = Column(String(20), default="open", nullable=False)  # open, acknowledged, resolved
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)
    metadata_json = Column(Text, nullable=True)  # Optional JSON metadata

    device = relationship("Device", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_device_ts", "device_id", "timestamp"),
        Index("ix_alerts_org_ts", "organization_id", "timestamp"),
        Index("ix_alerts_severity", "organization_id", "severity"),
    )

    def __repr__(self):
        return f"<Alert id={self.id} type={self.alert_type!r} severity={self.severity}>"


class AlertRule(Base):
    """
    Configurable alert rules evaluated against live telemetry.

    Each rule defines a metric, operator, threshold, and optional
    remediation action. Rules are scoped to an organization and
    optionally to a specific device.
    """
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=True,
    )
    name = Column(String(255), nullable=False)
    metric_name = Column(String(50), nullable=False)
    operator = Column(String(10), nullable=False)  # >, <, ==, >=, <=
    threshold_value = Column(Float, nullable=False)
    duration_seconds = Column(Integer, default=0)
    severity = Column(String(20), default="warning")
    action_type = Column(String(50), default="notification")
    action_target = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    organization = relationship("Organization", back_populates="alert_rules")

    def __repr__(self):
        return f"<AlertRule id={self.id} name={self.name!r} metric={self.metric_name}>"
