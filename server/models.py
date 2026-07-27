import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey, JSON, Index
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Organization(Base):
    """An enterprise organization containing users and devices."""
    __tablename__ = "organizations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    users = relationship("User", back_populates="organization", cascade="all, delete-orphan")
    devices = relationship("Device", back_populates="organization")

    def __repr__(self):
        return f"<Organization id={self.id} name={self.name}>"


class User(Base):
    """A user account with authentication and RBAC role (admin or user)."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    username = Column(String(100), unique=True, index=True, nullable=False)
    full_name = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
    role = Column(String(50), default="user", nullable=False)  # 'admin' or 'user'
    is_active = Column(Boolean, default=True, nullable=False)
    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    organization = relationship("Organization", back_populates="users")
    assigned_devices = relationship("Device", back_populates="assigned_user")

    def __repr__(self):
        return f"<User id={self.id} username={self.username} role={self.role}>"


class Device(Base):
    """A registered agent device."""
    __tablename__ = "devices"

    id = Column(Integer, primary_key=True, autoincrement=True)
    hostname = Column(String(255), nullable=False)
    os_name = Column(String(100), nullable=True)
    os_version = Column(String(100), nullable=True)
    api_key = Column(String(255), nullable=False)
    registered_at = Column(DateTime, default=datetime.datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    is_online = Column(Boolean, default=False)

    organization_id = Column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True)
    assigned_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Relationships
    organization = relationship("Organization", back_populates="devices")
    assigned_user = relationship("User", back_populates="assigned_devices")
    static_info = relationship("DeviceStaticInfo", back_populates="device", uselist=False, cascade="all, delete-orphan")
    metric_snapshots = relationship("MetricSnapshot", back_populates="device", cascade="all, delete-orphan")
    alerts = relationship("Alert", back_populates="device", cascade="all, delete-orphan")
    software = relationship("DeviceSoftware", back_populates="device", cascade="all, delete-orphan")

    def __repr__(self):
        return f"<Device id={self.id} hostname={self.hostname}>"


class DeviceStaticInfo(Base):
    """Hardware / OS specs for a device – one row per device, updated on registration."""
    __tablename__ = "device_static_info"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), unique=True, nullable=False)

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

    # Relationships
    device = relationship("Device", back_populates="static_info")


class MetricSnapshot(Base):
    """Time-series metric data point for a device."""
    __tablename__ = "metric_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    metrics = Column(JSON, nullable=False)  # Full metric payload as JSON

    device = relationship("Device", back_populates="metric_snapshots")

    __table_args__ = (
        Index("ix_metric_snapshots_device_ts", "device_id", "timestamp"),
    )


class Alert(Base):
    """Alert history for a device."""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    alert_type = Column(String(50), nullable=False)  # cpu, ram, disk, temp, network
    severity = Column(String(20), nullable=False)     # warning, critical
    message = Column(Text, nullable=False)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

    device = relationship("Device", back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_device_ts", "device_id", "timestamp"),
    )


class DeviceSoftware(Base):
    """Installed software list for a device."""
    __tablename__ = "device_software"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(500), nullable=False)
    version = Column(String(100), nullable=True)
    publisher = Column(String(255), nullable=True)
    install_date = Column(String(20), nullable=True)

    device = relationship("Device", back_populates="software")

    __table_args__ = (
        Index("ix_device_software_device", "device_id"),
    )


class AlertRule(Base):
    """User-defined intelligent alert rules with optional automated action triggers."""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=True)
    name = Column(String(255), nullable=False)
    metric_name = Column(String(50), nullable=False)
    operator = Column(String(10), nullable=False)
    threshold_value = Column(Float, nullable=False)
    duration_seconds = Column(Integer, default=0)
    severity = Column(String(20), default="warning")
    action_type = Column(String(50), default="notification")
    action_target = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class Incident(Base):
    """Incident history & automated remediation audit log."""
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=False)
    rule_id = Column(Integer, ForeignKey("alert_rules.id", ondelete="SET NULL"), nullable=True)
    title = Column(String(255), nullable=False)
    severity = Column(String(20), nullable=False)
    status = Column(String(30), default="open")
    action_taken = Column(String(100), nullable=True)
    log_output = Column(Text, nullable=True)
    triggered_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    resolved_at = Column(DateTime, nullable=True)

    device = relationship("Device")


class MaintenanceTask(Base):
    """Scheduled maintenance reminders and auto-cleanup tasks."""
    __tablename__ = "maintenance_tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    device_id = Column(Integer, ForeignKey("devices.id", ondelete="CASCADE"), nullable=True)
    title = Column(String(255), nullable=False)
    task_type = Column(String(50), nullable=False)
    frequency = Column(String(50), default="weekly")
    last_run = Column(DateTime, nullable=True)
    next_run = Column(DateTime, nullable=True)
    enabled = Column(Boolean, default=True)

