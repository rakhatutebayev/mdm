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
    metrics: Mapped[list["DeviceMetrics"]] = relationship(back_populates="device", cascade="all, delete-orphan", order_by="DeviceMetrics.recorded_at.desc()")


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
    model: Mapped[str] = mapped_column(String(255), default="")
    serial_number: Mapped[str] = mapped_column(String(255), default="")
    display_size: Mapped[str] = mapped_column(String(50), default="")
    resolution: Mapped[str] = mapped_column(String(50), default="")
    refresh_rate: Mapped[str] = mapped_column(String(20), default="")
    color_depth: Mapped[str] = mapped_column(String(20), default="")
    connection_type: Mapped[str] = mapped_column(String(100), default="")
    hdr_support: Mapped[bool] = mapped_column(Boolean, default=False)

    device: Mapped["Device"] = relationship(back_populates="monitors")


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


class EnrollmentToken(Base):
    __tablename__ = "enrollment_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(ForeignKey("customers.id", ondelete="CASCADE"))
    token: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    customer: Mapped["Customer"] = relationship(back_populates="enrollment_tokens")


class SystemSettings(Base):
    """Global key-value settings store. One row per setting key."""
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(String(500), default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

