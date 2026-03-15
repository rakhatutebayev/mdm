"""System settings router — GET/PUT key-value server configuration."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import SystemSettings

router = APIRouter(prefix="/api/v1/settings", tags=["settings"])

# ── Default values (used when no row exists in DB yet) ──────────────────────
DEFAULTS: dict[str, tuple[str, str]] = {
    "mdm_server_url":          ("https://mdm.nocko.com",  "Public MDM server URL used by agents and package builder"),
    "agent_checkin_interval":  ("300",                     "Legacy overall check-in interval"),
    "agent_heartbeat_interval": ("60",                     "Seconds between heartbeat updates"),
    "agent_metrics_interval":   ("120",                    "Seconds between metrics uploads"),
    "agent_inventory_interval": ("21600",                  "Seconds between full inventory uploads"),
    "agent_commands_interval":  ("45",                     "Seconds between command polling"),
    "agent_log_level":         ("INFO",                    "Agent log verbosity: DEBUG | INFO | WARNING | ERROR"),
    "smtp_host":               ("",                        "SMTP host for email notifications"),
    "smtp_port":               ("587",                     "SMTP port"),
    "smtp_user":               ("",                        "SMTP username"),
    "smtp_pass":               ("",                        "SMTP password"),
    "smtp_from":               ("noreply@mdm.nocko.com",   "From address for outgoing emails"),
    "enroll_auto_approve":     ("false",                   "Auto-approve new device enrollments"),
    "enroll_require_token":    ("true",                    "Require enrollment token"),
    "audit_log_enabled":       ("true",                    "Log admin actions to DB"),
    "siem_enabled":            ("false",                   "Forward events to SIEM endpoint"),
}


async def _get_all(db: AsyncSession) -> dict[str, str]:
    """Return all settings as a plain dict, falling back to defaults."""
    result = await db.execute(select(SystemSettings))
    rows = {r.key: r.value for r in result.scalars().all()}
    # Merge with defaults so we always return every key
    merged = {k: rows.get(k, default) for k, (default, _) in DEFAULTS.items()}
    return merged


async def get_server_url(db: AsyncSession) -> str:
    """Helper used by other routers to get the current MDM server URL."""
    result = await db.execute(
        select(SystemSettings).where(SystemSettings.key == "mdm_server_url")
    )
    row = result.scalar_one_or_none()
    import os
    return (row.value if row else None) or os.getenv("MDM_SERVER_URL", "https://mdm.nocko.com")


async def get_agent_package_settings(db: AsyncSession) -> dict[str, str]:
    """Return the subset of settings used to build tenant bootstrap config."""
    data = await _get_all(db)
    return {
        "server_url": data["mdm_server_url"].rstrip("/"),
        "heartbeat_interval": data.get("agent_heartbeat_interval", data["agent_checkin_interval"]),
        "metrics_interval": data.get("agent_metrics_interval", data["agent_checkin_interval"]),
        "inventory_interval": data.get("agent_inventory_interval", "21600"),
        "commands_interval": data.get("agent_commands_interval", "45"),
        "log_level": data["agent_log_level"],
        "siem_enabled": data["siem_enabled"],
    }


class SettingsOut(BaseModel):
    mdm_server_url: str
    agent_checkin_interval: str
    agent_heartbeat_interval: str
    agent_metrics_interval: str
    agent_inventory_interval: str
    agent_commands_interval: str
    agent_log_level: str
    smtp_host: str
    smtp_port: str
    smtp_user: str
    smtp_pass: str
    smtp_from: str
    enroll_auto_approve: bool
    enroll_require_token: bool
    audit_log_enabled: bool
    siem_enabled: bool


class SettingsIn(BaseModel):
    mdm_server_url: str | None = None
    agent_checkin_interval: str | None = None
    agent_heartbeat_interval: str | None = None
    agent_metrics_interval: str | None = None
    agent_inventory_interval: str | None = None
    agent_commands_interval: str | None = None
    agent_log_level: str | None = None
    smtp_host: str | None = None
    smtp_port: str | None = None
    smtp_user: str | None = None
    smtp_pass: str | None = None
    smtp_from: str | None = None
    enroll_auto_approve: bool | None = None
    enroll_require_token: bool | None = None
    audit_log_enabled: bool | None = None
    siem_enabled: bool | None = None


def _to_out(data: dict[str, str]) -> SettingsOut:
    return SettingsOut(
        mdm_server_url=data["mdm_server_url"],
        agent_checkin_interval=data["agent_checkin_interval"],
        agent_heartbeat_interval=data.get("agent_heartbeat_interval", data["agent_checkin_interval"]),
        agent_metrics_interval=data.get("agent_metrics_interval", data["agent_checkin_interval"]),
        agent_inventory_interval=data.get("agent_inventory_interval", "21600"),
        agent_commands_interval=data.get("agent_commands_interval", "45"),
        agent_log_level=data["agent_log_level"],
        smtp_host=data["smtp_host"],
        smtp_port=data["smtp_port"],
        smtp_user=data["smtp_user"],
        smtp_pass=data["smtp_pass"],
        smtp_from=data["smtp_from"],
        enroll_auto_approve=data["enroll_auto_approve"].lower() == "true",
        enroll_require_token=data["enroll_require_token"].lower() == "true",
        audit_log_enabled=data["audit_log_enabled"].lower() == "true",
        siem_enabled=data["siem_enabled"].lower() == "true",
    )


@router.get("", response_model=SettingsOut)
async def get_settings(db: AsyncSession = Depends(get_db)):
    """Return current system settings."""
    data = await _get_all(db)
    return _to_out(data)


@router.put("", response_model=SettingsOut)
async def update_settings(body: SettingsIn, db: AsyncSession = Depends(get_db)):
    """Update one or more settings. Only provided fields are changed."""
    updates: dict[str, str] = {}
    if body.mdm_server_url is not None:
        updates["mdm_server_url"] = body.mdm_server_url.rstrip("/")
    if body.agent_checkin_interval is not None:
        updates["agent_checkin_interval"] = body.agent_checkin_interval
    if body.agent_heartbeat_interval is not None:
        updates["agent_heartbeat_interval"] = body.agent_heartbeat_interval
    if body.agent_metrics_interval is not None:
        updates["agent_metrics_interval"] = body.agent_metrics_interval
    if body.agent_inventory_interval is not None:
        updates["agent_inventory_interval"] = body.agent_inventory_interval
    if body.agent_commands_interval is not None:
        updates["agent_commands_interval"] = body.agent_commands_interval
    if body.agent_log_level is not None:
        updates["agent_log_level"] = body.agent_log_level
    if body.smtp_host is not None:
        updates["smtp_host"] = body.smtp_host
    if body.smtp_port is not None:
        updates["smtp_port"] = body.smtp_port
    if body.smtp_user is not None:
        updates["smtp_user"] = body.smtp_user
    if body.smtp_pass is not None:
        updates["smtp_pass"] = body.smtp_pass
    if body.smtp_from is not None:
        updates["smtp_from"] = body.smtp_from
    if body.enroll_auto_approve is not None:
        updates["enroll_auto_approve"] = str(body.enroll_auto_approve).lower()
    if body.enroll_require_token is not None:
        updates["enroll_require_token"] = str(body.enroll_require_token).lower()
    if body.audit_log_enabled is not None:
        updates["audit_log_enabled"] = str(body.audit_log_enabled).lower()
    if body.siem_enabled is not None:
        updates["siem_enabled"] = str(body.siem_enabled).lower()

    for key, val in updates.items():
        result = await db.execute(select(SystemSettings).where(SystemSettings.key == key))
        row = result.scalar_one_or_none()
        if row:
            row.value = val
        else:
            desc = DEFAULTS.get(key, ("", ""))[1] if key in DEFAULTS else ""
            db.add(SystemSettings(key=key, value=val, description=desc))

    await db.commit()

    data = await _get_all(db)
    return _to_out(data)
