"""
Device Software Model
=====================

Records installed software on each monitored device, reported
by the agent during initial enrollment and periodic refreshes.

The full software list is replaced atomically on each upload
(DELETE all + INSERT new) rather than attempting diffs, because
the agent has the authoritative view of what's installed.
"""
import datetime
from sqlalchemy import Column, Integer, String, ForeignKey, Index
from sqlalchemy.orm import relationship
from server.models.base import Base


class DeviceSoftware(Base):
    __tablename__ = "device_software"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    name = Column(String(500), nullable=False)
    version = Column(String(100), nullable=True)
    publisher = Column(String(255), nullable=True)
    install_date = Column(String(20), nullable=True)

    device = relationship("Device", back_populates="software")

    __table_args__ = (
        Index("ix_device_software_device", "device_id"),
    )

    def __repr__(self):
        return f"<DeviceSoftware id={self.id} name={self.name!r}>"
