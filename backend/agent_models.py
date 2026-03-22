"""
Zabbix-style SQLAlchemy ORM models for the NOCKO Proxy Agent layer.
Implements all tables from portal_backend_tz.md Section 2.x.

Coexists alongside the existing Windows MDM models (models.py).
Uses the same async engine from database.py.

Production: PostgreSQL (asyncpg).
Dev/test:   SQLite (aiosqlite).
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Float, Integer,
    String, Text, UniqueConstraint, Index, ForeignKey,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


# ──────────────────────────────────────────────────────────────────────────────
# 2.1  tenants  (mirrors existing Customer but independent)
# ──────────────────────────────────────────────────────────────────────────────
class Tenant(Base):
    """
    Multi-tenant root. New devices and agents are scoped per tenant.
    Linked to existing Customer by customer_id (optional bridge).
    """
    __tablename__ = "agent_tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    customer_id: Mapped[Optional[str]] = mapped_column(String(36), nullable=True)  # FK to existing customers
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    agents: Mapped[list["Agent"]] = relationship(back_populates="tenant")
    profiles: Mapped[list["Profile"]] = relationship(back_populates="tenant")
    devices: Mapped[list["AgentDevice"]] = relationship(back_populates="tenant")


# ──────────────────────────────────────────────────────────────────────────────
# 2.2  agents
# ──────────────────────────────────────────────────────────────────────────────
class Agent(Base):
    """Proxy agent registration record. admin_status ≠ online (computed)."""
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("agent_tenants.id", ondelete="CASCADE"))
    site_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    version: Mapped[str] = mapped_column(String(50), default="")
    ip: Mapped[str] = mapped_column(String(45), default="")
    hostname: Mapped[str] = mapped_column(String(255), default="")
    admin_status: Mapped[str] = mapped_column(String(20), default="active")  # active|revoked|disabled
    last_seen: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    cert_fingerprint: Mapped[str] = mapped_column(String(255), default="")
    auth_token: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="agents")
    devices: Mapped[list["AgentDevice"]] = relationship(
        back_populates="owner_agent", foreign_keys="AgentDevice.device_owner_agent_id"
    )

    __table_args__ = (
        Index("ix_agents_tenant_last_seen", "tenant_id", "last_seen"),
    )

    @property
    def online(self) -> bool:
        """Computed: agent is online if heartbeat received within 3 minutes."""
        if not self.last_seen:
            return False
        return (int(time.time()) - self.last_seen) < 180


# ──────────────────────────────────────────────────────────────────────────────
# 2.3  profiles
# ──────────────────────────────────────────────────────────────────────────────
class Profile(Base):
    """Device profile (e.g. 'Dell iDRAC7', 'HPE ProLiant', 'Cisco IOS Switch')."""
    __tablename__ = "profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("agent_tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    vendor: Mapped[str] = mapped_column(String(255), default="")
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    description: Mapped[str] = mapped_column(Text, default="")
    schema_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="profiles")
    templates: Mapped[list["Template"]] = relationship(back_populates="profile", cascade="all, delete-orphan")
    devices: Mapped[list["AgentDevice"]] = relationship(back_populates="profile")

    __table_args__ = (
        UniqueConstraint("tenant_id", "vendor", "name", "version", name="uq_profiles_tenant_vendor_name_ver"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2.4  templates
# ──────────────────────────────────────────────────────────────────────────────
class Template(Base):
    """Template = collection of items (metric keys) within a profile."""
    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("agent_tenants.id", ondelete="CASCADE"))
    profile_id: Mapped[int] = mapped_column(ForeignKey("profiles.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")

    profile: Mapped["Profile"] = relationship(back_populates="templates")
    items: Mapped[list["Item"]] = relationship(back_populates="template", cascade="all, delete-orphan")
    device_templates: Mapped[list["DeviceTemplate"]] = relationship(back_populates="template")

    __table_args__ = (
        Index("ix_templates_tenant_profile", "tenant_id", "profile_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2.5  items
# ──────────────────────────────────────────────────────────────────────────────
class Item(Base):
    """
    Metric key definition within a template.
    Business rule: key must be unique within profile_id (enforced at app level in MVP).
    """
    __tablename__ = "items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("agent_tenants.id", ondelete="CASCADE"))
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), default="")
    value_type: Mapped[str] = mapped_column(String(20), default="uint")  # uint|float|string|text|log
    poll_class: Mapped[str] = mapped_column(String(20), default="fast")  # fast|slow|inventory|lld
    interval_sec: Mapped[int] = mapped_column(Integer, default=60)
    store_history: Mapped[bool] = mapped_column(Boolean, default=True)
    store_trends: Mapped[bool] = mapped_column(Boolean, default=True)

    template: Mapped["Template"] = relationship(back_populates="items")

    __table_args__ = (
        UniqueConstraint("template_id", "key", name="uq_items_template_key"),
        Index("ix_items_tenant_template", "tenant_id", "template_id"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2.6  devices (agent-managed, NOT the Windows MDM devices)
# ──────────────────────────────────────────────────────────────────────────────
class AgentDevice(Base):
    """
    Network device discovered and polled by proxy agent.
    device_uid = external identifier from payload (serial/uuid/MAC).
    online and health_status are computed, not stored.
    """
    __tablename__ = "agent_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    device_uid: Mapped[str] = mapped_column(String(255), nullable=False)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("agent_tenants.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(255), default="")
    profile_id: Mapped[Optional[int]] = mapped_column(ForeignKey("profiles.id"), nullable=True)
    device_owner_agent_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )
    ip: Mapped[str] = mapped_column(String(45), default="")
    mac: Mapped[str] = mapped_column(String(17), default="")
    serial: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    vendor: Mapped[str] = mapped_column(String(255), default="")
    device_class: Mapped[str] = mapped_column(String(50), default="")  # server|switch|printer...
    location: Mapped[str] = mapped_column(String(255), default="")
    last_seen: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    tenant: Mapped["Tenant"] = relationship(back_populates="devices")
    profile: Mapped[Optional["Profile"]] = relationship(back_populates="devices")
    owner_agent: Mapped[Optional["Agent"]] = relationship(
        back_populates="devices", foreign_keys=[device_owner_agent_id]
    )
    device_templates: Mapped[list["DeviceTemplate"]] = relationship(
        back_populates="device", cascade="all, delete-orphan"
    )
    inventory: Mapped[Optional["DeviceInventory"]] = relationship(
        back_populates="device", uselist=False, cascade="all, delete-orphan"
    )
    alerts: Mapped[list["Alert"]] = relationship(back_populates="device", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("tenant_id", "device_uid", name="uq_agent_devices_tenant_uid"),
        Index("ix_agent_devices_tenant_profile", "tenant_id", "profile_id"),
        Index("ix_agent_devices_tenant_agent", "tenant_id", "device_owner_agent_id"),
        Index("ix_agent_devices_tenant_serial", "tenant_id", "serial"),
        Index("ix_agent_devices_tenant_mac", "tenant_id", "mac"),
        Index("ix_agent_devices_tenant_ip", "tenant_id", "ip"),
    )

    @property
    def online(self) -> bool:
        if not self.last_seen:
            return False
        return (int(time.time()) - self.last_seen) < 300  # 5-minute threshold


# ──────────────────────────────────────────────────────────────────────────────
# 2.7  device_templates
# ──────────────────────────────────────────────────────────────────────────────
class DeviceTemplate(Base):
    """Explicit assignment of a template to a device. enabled = active polling."""
    __tablename__ = "device_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("agent_tenants.id", ondelete="CASCADE"))
    device_id: Mapped[int] = mapped_column(ForeignKey("agent_devices.id", ondelete="CASCADE"))
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    device: Mapped["AgentDevice"] = relationship(back_populates="device_templates")
    template: Mapped["Template"] = relationship(back_populates="device_templates")

    __table_args__ = (
        UniqueConstraint("tenant_id", "device_id", "template_id", name="uq_device_templates"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2.8  history_* — Universal metric value tables
# ──────────────────────────────────────────────────────────────────────────────
class _HistoryBase(Base):
    """Abstract base for all history tables."""
    __abstract__ = True

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[int] = mapped_column(Integer)
    clock: Mapped[int] = mapped_column(BigInteger, index=True)
    enqueue_ts: Mapped[int] = mapped_column(BigInteger)


class HistoryUint(_HistoryBase):
    __tablename__ = "history_uint"
    value: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (Index("ix_history_uint_lookup", "tenant_id", "device_id", "item_id", "clock"),)


class HistoryFloat(_HistoryBase):
    __tablename__ = "history_float"
    value: Mapped[float] = mapped_column(Float)

    __table_args__ = (Index("ix_history_float_lookup", "tenant_id", "device_id", "item_id", "clock"),)


class HistoryStr(_HistoryBase):
    __tablename__ = "history_str"
    value: Mapped[str] = mapped_column(String(255), default="")

    __table_args__ = (Index("ix_history_str_lookup", "tenant_id", "device_id", "item_id", "clock"),)


class HistoryText(_HistoryBase):
    __tablename__ = "history_text"
    value: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_history_text_lookup", "tenant_id", "device_id", "item_id", "clock"),)


class HistoryLog(_HistoryBase):
    __tablename__ = "history_log"
    value: Mapped[str] = mapped_column(Text, default="")

    __table_args__ = (Index("ix_history_log_lookup", "tenant_id", "device_id", "item_id", "clock"),)


# Map value_type string → history table class
HISTORY_TABLE_MAP: dict[str, type] = {
    "uint": HistoryUint,
    "float": HistoryFloat,
    "string": HistoryStr,
    "text": HistoryText,
    "log": HistoryLog,
}


# ──────────────────────────────────────────────────────────────────────────────
# 2.9  last_values — UI cache of latest metric value
# ──────────────────────────────────────────────────────────────────────────────
class LastValue(Base):
    """UI-only cache. Not for analytics. Source of truth is history_*."""
    __tablename__ = "last_values"

    device_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    value: Mapped[str] = mapped_column(Text, default="")
    clock: Mapped[int] = mapped_column(BigInteger, default=0)


# ──────────────────────────────────────────────────────────────────────────────
# 2.10  trends_*
# ──────────────────────────────────────────────────────────────────────────────
class TrendUint(Base):
    __tablename__ = "trends_uint"
    tenant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hour: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    min: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    max: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class TrendFloat(Base):
    __tablename__ = "trends_float"
    tenant_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    device_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    item_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hour: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    avg: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


# ──────────────────────────────────────────────────────────────────────────────
# 2.11  inventory
# ──────────────────────────────────────────────────────────────────────────────
class DeviceInventory(Base):
    """Current snapshot of device hardware. Upsert on every inventory payload."""
    __tablename__ = "device_inventory"

    device_id: Mapped[int] = mapped_column(
        ForeignKey("agent_devices.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[int] = mapped_column(Integer)
    last_agent_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    vendor: Mapped[str] = mapped_column(String(255), default="")
    model: Mapped[str] = mapped_column(String(255), default="")
    serial: Mapped[str] = mapped_column(String(255), default="")
    cpu_model: Mapped[str] = mapped_column(String(255), default="")
    ram_gb: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    disk_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    firmware_version: Mapped[str] = mapped_column(String(100), default="")
    data_json: Mapped[str] = mapped_column(Text, default="{}")
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())

    device: Mapped["AgentDevice"] = relationship(back_populates="inventory")


# ──────────────────────────────────────────────────────────────────────────────
# 2.12  events
# ──────────────────────────────────────────────────────────────────────────────
class Event(Base):
    """
    Immutable event log. dedup_key prevents replay duplicates.
    dedup_key = sha256(tenant_id + device_id + event_type + source + code + clock_bucket)
    """
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[int] = mapped_column(Integer)
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    agent_id: Mapped[int] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(50))   # trap|derived|threshold|agent|system
    source: Mapped[str] = mapped_column(String(255), default="")
    severity: Mapped[str] = mapped_column(String(20))     # info|warning|critical
    code: Mapped[str] = mapped_column(String(100), default="")
    message: Mapped[str] = mapped_column(Text, default="")
    dedup_key: Mapped[str] = mapped_column(String(64))
    clock: Mapped[int] = mapped_column(BigInteger)

    __table_args__ = (
        UniqueConstraint("tenant_id", "dedup_key", name="uq_events_tenant_dedup"),
        Index("ix_events_device_clock", "tenant_id", "device_id", "clock"),
        Index("ix_events_severity", "tenant_id", "severity", "clock"),
    )

    @staticmethod
    def make_dedup_key(tenant_id: int, device_id: int, event_type: str,
                       source: str, code: str, clock: int, bucket_sec: int = 60) -> str:
        clock_bucket = (clock // bucket_sec) * bucket_sec
        raw = f"{tenant_id}:{device_id}:{event_type}:{source}:{code}:{clock_bucket}"
        return hashlib.sha256(raw.encode()).hexdigest()[:64]


# ──────────────────────────────────────────────────────────────────────────────
# 2.13  alerts
# ──────────────────────────────────────────────────────────────────────────────
class Alert(Base):
    """
    Alert lifecycle: opened → closed.
    Never deleted — history of closed alerts kept for audit.
    health_status of device = max severity WHERE active=true.
    """
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    device_id: Mapped[int] = mapped_column(ForeignKey("agent_devices.id", ondelete="CASCADE"))
    item_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)   # NULL allowed
    severity: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(255), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    opened_at: Mapped[int] = mapped_column(BigInteger)
    closed_at: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)

    device: Mapped["AgentDevice"] = relationship(back_populates="alerts")

    __table_args__ = (
        Index("ix_alerts_active", "tenant_id", "device_id", "active"),
        Index("ix_alerts_severity_active", "tenant_id", "active", "severity"),
    )


# ──────────────────────────────────────────────────────────────────────────────
# 2.14  audit_log
# ──────────────────────────────────────────────────────────────────────────────
class AgentAuditLog(Base):
    __tablename__ = "agent_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    action: Mapped[str] = mapped_column(String(100))
    actor: Mapped[str] = mapped_column(String(255), default="system")
    entity_type: Mapped[str] = mapped_column(String(50), default="")
    entity_id: Mapped[str] = mapped_column(String(255), default="")
    details: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


# ──────────────────────────────────────────────────────────────────────────────
# 2.15  commands + command_results
# ──────────────────────────────────────────────────────────────────────────────
class AgentCommand(Base):
    __tablename__ = "agent_commands"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id", ondelete="CASCADE"))
    command_id: Mapped[str] = mapped_column(String(36), unique=True, nullable=False)  # UUID v4
    command_type: Mapped[str] = mapped_column(String(100))
    issued_at: Mapped[int] = mapped_column(BigInteger)
    issued_by: Mapped[str] = mapped_column(String(255), default="portal")
    payload: Mapped[str] = mapped_column(Text, default="{}")
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending|acked|done|failed

    results: Mapped[list["AgentCommandResult"]] = relationship(back_populates="command")

    __table_args__ = (
        Index("ix_agent_commands_tenant_agent", "tenant_id", "agent_id", "issued_at"),
    )


class AgentCommandResult(Base):
    __tablename__ = "agent_command_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    command_id: Mapped[str] = mapped_column(
        ForeignKey("agent_commands.command_id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[int] = mapped_column(Integer)
    agent_id: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(Text, default="")
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    finished_at: Mapped[int] = mapped_column(BigInteger)

    command: Mapped["AgentCommand"] = relationship(back_populates="results")
