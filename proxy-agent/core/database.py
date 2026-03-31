"""
SQLite local database for NOCKO Proxy Agent.
14 tables as specified in proxy_agent_tz.md Section 6.5.

Engine: SQLite with check_same_thread=False for async FastAPI use.
ORM: SQLModel (Pydantic + SQLAlchemy unified).
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Optional

from sqlalchemy import text
from sqlmodel import Field, SQLModel, Session, create_engine, select
from core.logger import log


# ──────────────────────────────────────────────────────────────────────────────
# 1. queue_items — Offline send queue
# ──────────────────────────────────────────────────────────────────────────────
class QueueItem(SQLModel, table=True):
    __tablename__ = "queue_items"

    id: Optional[int] = Field(default=None, primary_key=True)
    type: str = Field(index=True)                       # metrics / inventory / events / heartbeat
    device_id: Optional[str] = Field(default=None, index=True)
    payload: str = Field(default="{}")                  # JSON string (envelope)
    status: str = Field(default="pending", index=True)  # pending | sent | failed
    attempts: int = Field(default=0)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    enqueue_timestamp: int = Field(default=0)           # Unix timestamp (UTC)


# ──────────────────────────────────────────────────────────────────────────────
# 2. device_profiles — Loaded profiles
# ──────────────────────────────────────────────────────────────────────────────
class DeviceProfile(SQLModel, table=True):
    __tablename__ = "device_profiles"

    id: Optional[int] = Field(default=None, primary_key=True)
    profile_id: str = Field(unique=True, index=True)    # slug
    profile_name: str = Field(default="")
    profile_vendor: str = Field(default="")
    profile_version: str = Field(default="")
    output_mapping: str = Field(default="[]")           # JSON array of output_mapping objects
    # Zabbix template description + agent_playbook + stats (JSON), set on import
    import_meta_json: str = Field(default="{}")
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 3. devices — Polled devices
# ──────────────────────────────────────────────────────────────────────────────
class Device(SQLModel, table=True):
    __tablename__ = "devices"

    id: Optional[int] = Field(default=None, primary_key=True)
    ip: str = Field(index=True)
    device_id: str = Field(unique=True, index=True)     # fingerprint = device_uid
    profile_id: Optional[str] = Field(default=None, index=True, foreign_key="device_profiles.profile_id")
    # Collector type: "snmp" (default) or "vmware"
    collector_type: str = Field(default="snmp")
    # SNMP fields
    snmp_version: str = Field(default="2c")             # 2c | 3
    snmp_community: str = Field(default="public")
    snmp_v3_user: str = Field(default="")
    snmp_v3_auth_key: str = Field(default="")
    snmp_v3_priv_key: str = Field(default="")
    # VMware fields
    vmware_url: str = Field(default="")                 # https://esxi-ip/sdk
    vmware_username: str = Field(default="")
    vmware_password: str = Field(default="")
    poll_interval_fast: int = Field(default=60)
    poll_interval_slow: int = Field(default=300)
    poll_interval_inventory: int = Field(default=86400)
    last_seen: Optional[int] = Field(default=None)      # Unix timestamp
    status: str = Field(default="active")               # active | unsupported | offline


# ──────────────────────────────────────────────────────────────────────────────
# 4. agent_config — Key-value store for SERVER-MANAGED config
# ──────────────────────────────────────────────────────────────────────────────
class AgentConfigKV(SQLModel, table=True):
    __tablename__ = "agent_config"

    key: str = Field(primary_key=True)
    value: str = Field(default="")


# ──────────────────────────────────────────────────────────────────────────────
# 5. commands — Incoming commands from portal
# ──────────────────────────────────────────────────────────────────────────────
class Command(SQLModel, table=True):
    __tablename__ = "commands"

    id: Optional[int] = Field(default=None, primary_key=True)
    command_id: str = Field(unique=True, index=True)    # UUID v4 from portal
    command_type: str = Field(default="")               # reload_config | update_agent | ...
    issued_at: int = Field(default=0)                   # Unix timestamp
    issued_by: str = Field(default="")
    payload: str = Field(default="{}")                  # JSON
    status: str = Field(default="pending")              # pending | running | done | failed
    received_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 6. command_results
# ──────────────────────────────────────────────────────────────────────────────
class CommandResult(SQLModel, table=True):
    __tablename__ = "command_results"

    id: Optional[int] = Field(default=None, primary_key=True)
    command_id: str = Field(index=True)                 # FK → commands.command_id
    status: str = Field(default="")                     # done | failed
    result: str = Field(default="")
    error_message: Optional[str] = Field(default=None)
    finished_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 7. trap_archive — Write-ahead journal for raw SNMP traps
# ──────────────────────────────────────────────────────────────────────────────
class TrapArchive(SQLModel, table=True):
    __tablename__ = "trap_archive"

    id: Optional[int] = Field(default=None, primary_key=True)
    oid: str = Field(default="")
    source_ip: str = Field(default="")
    raw_data: str = Field(default="{}")                 # JSON representation
    received_at: datetime = Field(default_factory=datetime.utcnow)
    forwarded_at: Optional[datetime] = Field(default=None)


# ──────────────────────────────────────────────────────────────────────────────
# 8. profile_import_logs — Template import/conversion log
# ──────────────────────────────────────────────────────────────────────────────
class ProfileImportLog(SQLModel, table=True):
    __tablename__ = "profile_import_logs"

    id: Optional[int] = Field(default=None, primary_key=True)
    filename: str = Field(default="")
    profile_id: Optional[str] = Field(default=None)
    status: str = Field(default="ok")                   # ok | error | partial
    warnings: str = Field(default="[]")                 # JSON array of warning strings
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 9. config_versions — History of applied server configs
# ──────────────────────────────────────────────────────────────────────────────
class ConfigVersion(SQLModel, table=True):
    __tablename__ = "config_versions"

    id: Optional[int] = Field(default=None, primary_key=True)
    version: str = Field(default="")
    config_json: str = Field(default="{}")
    applied_at: datetime = Field(default_factory=datetime.utcnow)
    applied_by: str = Field(default="server")           # server | manual


# ──────────────────────────────────────────────────────────────────────────────
# 10. inventory_cache — Latest inventory snapshot per device
# ──────────────────────────────────────────────────────────────────────────────
class InventoryCache(SQLModel, table=True):
    __tablename__ = "inventory_cache"

    device_id: str = Field(primary_key=True)
    data_json: str = Field(default="{}")
    collected_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 11. lld_cache — LLD discovery cache
# ──────────────────────────────────────────────────────────────────────────────
class LLDCache(SQLModel, table=True):
    __tablename__ = "lld_cache"

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True)
    key: str = Field(index=True)
    value_json: str = Field(default="[]")
    discovered_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 12. metric_rollups — Hourly aggregates (downsampling)
# ──────────────────────────────────────────────────────────────────────────────
class MetricRollup(SQLModel, table=True):
    __tablename__ = "metric_rollups"

    id: Optional[int] = Field(default=None, primary_key=True)
    device_id: str = Field(index=True)
    item_key: str = Field(index=True)
    hour: int = Field(index=True)                        # Unix timestamp of hour start
    min_val: Optional[float] = Field(default=None)
    max_val: Optional[float] = Field(default=None)
    avg_val: Optional[float] = Field(default=None)
    count: int = Field(default=0)


# ──────────────────────────────────────────────────────────────────────────────
# 13. audit_log — Admin actions via Local UI
# ──────────────────────────────────────────────────────────────────────────────
class AuditLog(SQLModel, table=True):
    __tablename__ = "audit_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    action: str = Field(default="")                     # add_device | load_profile | ...
    actor: str = Field(default="local_ui")
    details: str = Field(default="{}")                  # JSON
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ──────────────────────────────────────────────────────────────────────────────
# 14. agent_cert_meta — Certificate rotation metadata
# ──────────────────────────────────────────────────────────────────────────────
class AgentCertMeta(SQLModel, table=True):
    __tablename__ = "agent_cert_meta"

    id: Optional[int] = Field(default=None, primary_key=True)
    cert_type: str = Field(default="transport")         # transport | ui
    issued_at: Optional[datetime] = Field(default=None)
    expires_at: Optional[datetime] = Field(default=None)
    fingerprint: str = Field(default="")
    last_rotated_at: Optional[datetime] = Field(default=None)
    rotation_status: str = Field(default="ok")          # ok | pending | failed


# ──────────────────────────────────────────────────────────────────────────────
# Engine + helpers
# ──────────────────────────────────────────────────────────────────────────────
_engine = None


def _migrate_device_profiles_columns(engine) -> None:
    """Add columns introduced after first release (SQLite has no ALTER complex)."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(device_profiles)"))
            cols = {row[1] for row in r.fetchall()}
            if "import_meta_json" not in cols:
                conn.execute(
                    text(
                        "ALTER TABLE device_profiles ADD COLUMN import_meta_json TEXT NOT NULL DEFAULT '{}'"
                    )
                )
                log.info("SQLite migration: device_profiles.import_meta_json added")
    except Exception as e:
        log.warning(f"SQLite migration device_profiles: {e}")


def _migrate_devices_columns(engine) -> None:
    """Add VMware + collector_type columns to devices table (added after initial release)."""
    try:
        with engine.begin() as conn:
            r = conn.execute(text("PRAGMA table_info(devices)"))
            cols = {row[1] for row in r.fetchall()}
            migrations = [
                ("collector_type", "TEXT NOT NULL DEFAULT 'snmp'"),
                ("vmware_url", "TEXT NOT NULL DEFAULT ''"),
                ("vmware_username", "TEXT NOT NULL DEFAULT ''"),
                ("vmware_password", "TEXT NOT NULL DEFAULT ''"),
            ]
            for col, definition in migrations:
                if col not in cols:
                    conn.execute(text(f"ALTER TABLE devices ADD COLUMN {col} {definition}"))
                    log.info(f"SQLite migration: devices.{col} added")
    except Exception as e:
        log.warning(f"SQLite migration devices: {e}")


def init_db(db_path: str) -> None:
    """Create engine and all tables. Call once at startup."""
    global _engine
    url = f"sqlite:///{db_path}"
    _engine = create_engine(url, connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(_engine)
    _migrate_device_profiles_columns(_engine)
    _migrate_devices_columns(_engine)
    log.info(f"SQLite DB initialised at {db_path}")


def get_session() -> Session:
    """Return a new SQLModel session. Caller is responsible for closing."""
    if _engine is None:
        raise RuntimeError("DB not initialised. Call init_db() first.")
    return Session(_engine)


def kv_get(key: str, default: str = "") -> str:
    """Read a value from agent_config key-value store."""
    with get_session() as s:
        row = s.get(AgentConfigKV, key)
        return row.value if row else default


def kv_set(key: str, value: str) -> None:
    """Upsert a value in agent_config key-value store."""
    with get_session() as s:
        row = s.get(AgentConfigKV, key)
        if row:
            row.value = value
        else:
            s.add(AgentConfigKV(key=key, value=value))
        s.commit()


def kv_delete(key: str) -> None:
    """Remove a key from agent_config if present."""
    with get_session() as s:
        row = s.get(AgentConfigKV, key)
        if row:
            s.delete(row)
            s.commit()
