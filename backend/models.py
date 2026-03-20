"""SQLAlchemy ORM models for NOCKO MDM."""
from __future__ import annotations
import uuid
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Boolean, DateTime, ForeignKey, Integer, Text, func
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


def new_uuid() -> str:
    return str(uuid.uuid4())


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    devices: Mapped[list["Device"]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    enrollment_tokens: Mapped[list["EnrollmentToken"]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    proxy_agents: Mapped[list["ProxyAgent"]] = relationship(back_populates="customer", cascade="all, delete-orphan")
    discovered_assets: Mapped[list["DiscoveredAsset"]] = relationship(back_populates="customer", cascade="all, delete-orphan")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    device_name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(50))          # Windows, macOS, iOS, Android
    device_type: Mapped[str] = mapped_column(String(50), default="Desktop")
    model: Mapped[str] = mapped_column(String(255), default="")
    manufacturer: Mapped[str] = mapped_column(String(255), default="")
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    udid: Mapped[str] = mapped_column(String(255), default="")
    os_version: Mapped[str] = mapped_column(String(100), default="")
    architecture: Mapped[str] = mapped_column(String(50), default="")
    shared_device: Mapped[bool] = mapped_column(Boolean, default=False)
    owner: Mapped[str] = mapped_column(String(255), default="")
    enrollment_method: Mapped[str] = mapped_column(String(100), default="Agent")
    status: Mapped[str] = mapped_column(String(50), default="Pending")  # Pending | Enrolled | Deprovisioned | Failed
    enrolled_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_checkin: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    agent_version: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="devices")
    network: Mapped["NetworkInfo | None"] = relationship(back_populates="device", uselist=False, cascade="all, delete-orphan")
    monitors: Mapped[list["MonitorInfo"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    hardware_inventory: Mapped["HardwareInventory | None"] = relationship(back_populates="device", uselist=False, cascade="all, delete-orphan")
    physical_disks: Mapped[list["PhysicalDisk"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    logical_disks: Mapped[list["LogicalDisk"]] = relationship(back_populates="device", cascade="all, delete-orphan")
    metrics: Mapped[list["DeviceMetrics"]] = relationship(back_populates="device", cascade="all, delete-orphan", order_by="DeviceMetrics.recorded_at.desc()")
    printers: Mapped[list["PrinterInfo"]] = relationship(back_populates="device", cascade="all, delete-orphan")


class NetworkInfo(Base):
    __tablename__ = "network_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    mac_address: Mapped[str] = mapped_column(String(17), default="")
    hostname: Mapped[str] = mapped_column(String(255), default="")
    wifi_ssid: Mapped[str] = mapped_column(String(255), default="")
    connection_type: Mapped[str] = mapped_column(String(100), default="")
    dns_server: Mapped[str] = mapped_column(String(255), default="")
    default_gateway: Mapped[str] = mapped_column(String(45), default="")

    device: Mapped["Device"] = relationship(back_populates="network")


class MonitorInfo(Base):
    __tablename__ = "monitor_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    display_index: Mapped[int] = mapped_column(Integer, default=1)
    manufacturer: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    display_size: Mapped[str] = mapped_column(String(50), default="")
    resolution: Mapped[str] = mapped_column(String(50), default="")
    refresh_rate: Mapped[str] = mapped_column(String(20), default="")
    color_depth: Mapped[str] = mapped_column(String(20), default="")
    connection_type: Mapped[str] = mapped_column(String(100), default="")
    hdr_support: Mapped[bool] = mapped_column(Boolean, default=False)

    device: Mapped["Device"] = relationship(back_populates="monitors")


class HardwareInventory(Base):
    __tablename__ = "hardware_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"), unique=True)
    processor_model: Mapped[str] = mapped_column(String(255), default="")
    processor_vendor: Mapped[str] = mapped_column(String(255), default="")
    physical_cores: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    logical_processors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_total_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    memory_slot_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_slots_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_module_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    machine_class: Mapped[str] = mapped_column(String(50), default="")
    chassis_type: Mapped[str] = mapped_column(String(50), default="")
    gpu_model: Mapped[str] = mapped_column(String(255), default="")
    gpu_manufacturer: Mapped[str] = mapped_column(String(100), default="")
    gpu_vram_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    gpu_driver_version: Mapped[str] = mapped_column(String(100), default="")

    device: Mapped["Device"] = relationship(back_populates="hardware_inventory")


class PhysicalDisk(Base):
    __tablename__ = "physical_disks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    disk_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[str] = mapped_column(String(255), default="")
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    media_type: Mapped[str] = mapped_column(String(100), default="")
    interface_type: Mapped[str] = mapped_column(String(100), default="")
    size_gb: Mapped[Optional[float]] = mapped_column(nullable=True)

    device: Mapped["Device"] = relationship(back_populates="physical_disks")


class LogicalDisk(Base):
    __tablename__ = "logical_disks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50), default="")
    volume_name: Mapped[str] = mapped_column(String(255), default="")
    file_system: Mapped[str] = mapped_column(String(50), default="")
    drive_type: Mapped[str] = mapped_column(String(100), default="")
    size_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    free_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    used_gb: Mapped[Optional[float]] = mapped_column(nullable=True)

    device: Mapped["Device"] = relationship(back_populates="logical_disks")


class PrinterInfo(Base):
    __tablename__ = "printer_info"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), default="")
    driver_name: Mapped[str] = mapped_column(String(255), default="")
    port_name: Mapped[str] = mapped_column(String(255), default="")
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    is_network: Mapped[bool] = mapped_column(Boolean, default=False)
    is_shared: Mapped[bool] = mapped_column(Boolean, default=False)
    work_offline: Mapped[bool] = mapped_column(Boolean, default=False)
    job_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    connection_type: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(100), default="")

    device: Mapped["Device"] = relationship(back_populates="printers")


class DeviceMetrics(Base):
    """One telemetry snapshot per checkin (keep latest ~48 per device)."""
    __tablename__ = "device_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    # CPU
    cpu_pct: Mapped[Optional[float]] = mapped_column(nullable=True)

    # RAM
    ram_used_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    ram_total_gb: Mapped[Optional[float]] = mapped_column(nullable=True)

    # Disk C:
    disk_used_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    disk_total_gb: Mapped[Optional[float]] = mapped_column(nullable=True)

    # System
    uptime_seconds: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    os_version: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    device: Mapped["Device"] = relationship(back_populates="metrics")
    disk_metrics: Mapped[list["LogicalDiskMetric"]] = relationship(back_populates="snapshot", cascade="all, delete-orphan")


class LogicalDiskMetric(Base):
    __tablename__ = "logical_disk_metrics"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    metric_id: Mapped[int] = mapped_column(ForeignKey("device_metrics.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(50), default="")
    volume_name: Mapped[str] = mapped_column(String(255), default="")
    file_system: Mapped[str] = mapped_column(String(50), default="")
    drive_type: Mapped[str] = mapped_column(String(100), default="")
    size_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    free_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    used_gb: Mapped[Optional[float]] = mapped_column(nullable=True)

    snapshot: Mapped["DeviceMetrics"] = relationship(back_populates="disk_metrics")


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="enrollment_tokens")


class ProxyAgent(Base):
    __tablename__ = "proxy_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    site_name: Mapped[str] = mapped_column(String(255), default="")
    hostname: Mapped[str] = mapped_column(String(255), default="")
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    mac_address: Mapped[str] = mapped_column(String(17), default="")
    portal_url: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(50), default="")
    status: Mapped[str] = mapped_column(String(50), default="offline")
    is_registered: Mapped[bool] = mapped_column(Boolean, default=False)
    capabilities: Mapped[str] = mapped_column(Text, default="")
    auth_token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    last_checkin: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    registered_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="proxy_agents")
    assets: Mapped[list["DiscoveredAsset"]] = relationship(back_populates="proxy_agent")
    commands: Mapped[list["ProxyAgentCommand"]] = relationship(back_populates="proxy_agent", cascade="all, delete-orphan")


class DiscoveredAsset(Base):
    __tablename__ = "discovered_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    proxy_agent_id: Mapped[Optional[str]] = mapped_column(ForeignKey("proxy_agents.id", ondelete="SET NULL"), nullable=True)
    asset_class: Mapped[str] = mapped_column(String(50), default="network")
    source_type: Mapped[str] = mapped_column(String(50), default="proxy_agent")
    display_name: Mapped[str] = mapped_column(String(255), default="")
    vendor: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    firmware_version: Mapped[str] = mapped_column(String(100), default="")
    ip_address: Mapped[str] = mapped_column(String(45), default="")
    management_ip: Mapped[str] = mapped_column(String(45), default="")
    mac_address: Mapped[str] = mapped_column(String(17), default="")
    status: Mapped[str] = mapped_column(String(50), default="Discovered")
    raw_facts: Mapped[str] = mapped_column(Text, default="{}")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="discovered_assets")
    proxy_agent: Mapped["ProxyAgent | None"] = relationship(back_populates="assets")
    inventory: Mapped["AssetInventory | None"] = relationship(
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )
    components: Mapped[list["AssetComponent"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
    )
    health: Mapped["AssetHealth | None"] = relationship(
        back_populates="asset",
        uselist=False,
        cascade="all, delete-orphan",
    )
    alerts: Mapped[list["AssetAlert"]] = relationship(
        back_populates="asset",
        cascade="all, delete-orphan",
    )


class AssetInventory(Base):
    __tablename__ = "asset_inventory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("discovered_assets.id", ondelete="CASCADE"), unique=True)
    processor_model: Mapped[str] = mapped_column(String(255), default="")
    processor_vendor: Mapped[str] = mapped_column(String(255), default="")
    processor_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    physical_cores: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    logical_processors: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_total_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    memory_slot_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_slots_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    memory_module_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    storage_controller_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    physical_disk_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    virtual_disk_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    disk_total_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    network_interface_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    power_supply_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    raid_summary: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    asset: Mapped["DiscoveredAsset"] = relationship(back_populates="inventory")


class AssetComponent(Base):
    __tablename__ = "asset_components"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("discovered_assets.id", ondelete="CASCADE"))
    component_type: Mapped[str] = mapped_column(String(50), default="")
    name: Mapped[str] = mapped_column(String(255), default="")
    slot: Mapped[str] = mapped_column(String(100), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    manufacturer: Mapped[str] = mapped_column(String(255), default="")
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    firmware_version: Mapped[str] = mapped_column(String(100), default="")
    capacity_gb: Mapped[Optional[float]] = mapped_column(nullable=True)
    status: Mapped[str] = mapped_column(String(100), default="")
    health: Mapped[str] = mapped_column(String(100), default="")
    extra_json: Mapped[str] = mapped_column(Text, default="{}")

    asset: Mapped["DiscoveredAsset"] = relationship(back_populates="components")


class AssetHealth(Base):
    __tablename__ = "asset_health"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("discovered_assets.id", ondelete="CASCADE"), unique=True)
    overall_status: Mapped[str] = mapped_column(String(100), default="")
    processor_status: Mapped[str] = mapped_column(String(100), default="")
    memory_status: Mapped[str] = mapped_column(String(100), default="")
    storage_status: Mapped[str] = mapped_column(String(100), default="")
    power_status: Mapped[str] = mapped_column(String(100), default="")
    network_status: Mapped[str] = mapped_column(String(100), default="")
    thermal_status: Mapped[str] = mapped_column(String(100), default="")
    power_state: Mapped[str] = mapped_column(String(100), default="")
    alert_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    asset: Mapped["DiscoveredAsset"] = relationship(back_populates="health")


class AssetAlert(Base):
    __tablename__ = "asset_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("discovered_assets.id", ondelete="CASCADE"))
    source: Mapped[str] = mapped_column(String(100), default="")
    severity: Mapped[str] = mapped_column(String(50), default="")
    code: Mapped[str] = mapped_column(String(100), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(50), default="active")
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    extra_json: Mapped[str] = mapped_column(Text, default="{}")

    asset: Mapped["DiscoveredAsset"] = relationship(back_populates="alerts")


class ProxyAgentCommand(Base):
    __tablename__ = "proxy_agent_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    proxy_agent_id: Mapped[str] = mapped_column(ForeignKey("proxy_agents.id", ondelete="CASCADE"))
    command_type: Mapped[str] = mapped_column(String(100), nullable=False)
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    proxy_agent: Mapped["ProxyAgent"] = relationship(back_populates="commands")


class SystemSettings(Base):
    """Global key-value settings store. One row per setting key."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class DeviceCommand(Base):
    """MDM command queued for a device (e.g. rename_computer).

    Lifecycle: pending → sent → acked | failed
    """
    __tablename__ = "device_commands"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id", ondelete="CASCADE"))
    command_type: Mapped[str] = mapped_column(String(100), nullable=False)   # e.g. "rename_computer"
    payload: Mapped[str] = mapped_column(Text, nullable=False, default="{}")  # JSON string
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    result: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    acked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    device: Mapped["Device"] = relationship()
