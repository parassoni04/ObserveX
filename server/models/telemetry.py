"""
Telemetry Models
================

DeviceStaticInfo: One-time hardware/OS information reported by the agent
                  at startup (CPU model, RAM size, GPU, motherboard, etc.).

MetricSnapshot:   Time-series metric data points. Each snapshot contains a
                  JSON blob of live metrics (CPU%, RAM%, disk I/O, etc.)
                  at a specific timestamp.

Design notes:
- MetricSnapshot uses a composite index on (device_id, timestamp) for
  efficient time-range queries and retention cleanup.
- DeviceStaticInfo is 1:1 with Device (unique constraint on device_id).
- Both carry organization_id for efficient tenant-scoped queries without
  joining through Device every time.
"""
import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, JSON, Index
from sqlalchemy.orm import relationship
from server.models.base import Base


class DeviceStaticInfo(Base):
    __tablename__ = "device_static_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    computer_name = Column(String(255), nullable=True)
    os_release = Column(String(100), nullable=True)
    cpu_model = Column(String(255), nullable=True)
    cpu_cores_physical = Column(Integer, nullable=True)
    cpu_cores_logical = Column(Integer, nullable=True)
    total_ram_gb = Column(Float, nullable=True)
    gpu_model = Column(String(500), nullable=True)
    motherboard_mfg = Column(String(255), nullable=True)
    motherboard_product = Column(String(255), nullable=True)
    bios_name = Column(String(255), nullable=True)
    bios_version = Column(String(255), nullable=True)
    storage_devices = Column(JSON, nullable=True)
    network_adapters = Column(JSON, nullable=True)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

    device = relationship("Device", back_populates="static_info")


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(
        Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False,
    )
    organization_id = Column(
        Integer, ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    metrics = Column(JSON, nullable=False)

    device = relationship("Device", back_populates="metric_snapshots")

    __table_args__ = (
        Index("ix_metric_snapshots_device_ts", "device_id", "timestamp"),
        Index("ix_metric_snapshots_org_ts", "organization_id", "timestamp"),
    )
