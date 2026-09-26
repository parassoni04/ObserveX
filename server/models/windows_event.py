"""
Windows Event Model
===================

Stores Windows Event Log entries uploaded by agents. Events are kept
in-memory by the WebSocket hub for real-time dashboard access, and
optionally persisted to the database for historical analysis.

Events are scoped to a device and organization.
"""
import datetime
from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.models.base import Base


class WindowsEvent(Base):
    __tablename__ = "windows_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    log_type = Column(String(50), nullable=False)      # Application, System, Security
    source = Column(String(255), nullable=False)        # Event source name
    event_id = Column(Integer, nullable=True)
    severity = Column(String(20), nullable=False)       # Information, Warning, Error, Critical
    message = Column(Text, nullable=True)
    event_timestamp = Column(DateTime, nullable=True)   # When the event originally occurred
    received_at = Column(DateTime, default=datetime.datetime.utcnow)

    device = relationship("Device", back_populates="windows_events")

    __table_args__ = (
        Index("ix_windows_events_device_ts", "device_id", "received_at"),
        Index("ix_windows_events_org", "organization_id"),
    )

    def __repr__(self):
        return f"<WindowsEvent id={self.id} source={self.source!r} severity={self.severity}>"
