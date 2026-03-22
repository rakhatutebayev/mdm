"""
Portal-facing API for managing the Proxy Agent layer.
Used by the portal UI and admin dashboards.

Routes:
  Agents:
    GET  /api/v1/portal/agents                  ← list agents
    GET  /api/v1/portal/agents/{id}             ← agent detail + computed online
    POST /api/v1/portal/agents/{id}/command     ← issue command to agent
    PATCH /api/v1/portal/agents/{id}/status     ← change admin_status

  Devices:
    GET  /api/v1/portal/devices                 ← list devices (with computed health_status)
    GET  /api/v1/portal/devices/{id}            ← device detail + last_values + inventory
    GET  /api/v1/portal/devices/{id}/history    ← history_* values for an item
    GET  /api/v1/portal/devices/{id}/alerts     ← active and recent alerts

  Profiles:
    GET  /api/v1/portal/profiles                ← list profiles
    POST /api/v1/portal/profiles                ← create profile
    GET  /api/v1/portal/profiles/{id}/templates ← templates in profile
    POST /api/v1/portal/profiles/{id}/templates ← create template
    POST /api/v1/portal/templates/{id}/items    ← add item to template
    POST /api/v1/portal/devices/{id}/templates  ← assign template to device

  Alerts:
    GET  /api/v1/portal/alerts                  ← all active alerts (tenant-wide)
    POST /api/v1/portal/alerts/{id}/close       ← manually close alert

Auth: JWT / session from existing portal auth (placeholder: customer_id from header).
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select, func, and_, desc
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from zabbix_importer import parse_zabbix_template
from agent_models import (
    Agent, AgentDevice, Profile, Template, Item, DeviceTemplate,
    DeviceInventory, Event, Alert, AgentCommand, AgentCommandResult,
    LastValue, HISTORY_TABLE_MAP, Tenant, AgentAuditLog,
)

router = APIRouter(prefix="/api/v1/portal", tags=["Portal Agent API"])

_ONLINE_THRESHOLD_AGENT = 180    # 3 min
_ONLINE_THRESHOLD_DEVICE = 300   # 5 min


# ─── Simple tenant resolver (MVP: use X-Tenant-Id header) ──────────────────
async def _get_tenant_id(x_tenant_id: Optional[str] = Header(None)) -> int:
    """
    MVP auth: tenant_id from X-Tenant-Id header.
    Replace with JWT validation in production.
    """
    if not x_tenant_id:
        raise HTTPException(status_code=401, detail="X-Tenant-Id header required")
    try:
        return int(x_tenant_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="X-Tenant-Id must be an integer")


# ─── Pydantic schemas ──────────────────────────────────────────────────────
class IssueCommandRequest(BaseModel):
    command_type: str
    payload: dict = {}
    issued_by: str = "portal_user"


class CreateProfileRequest(BaseModel):
    name: str
    vendor: str = ""
    version: str = "1.0.0"
    description: str = ""


class CreateTemplateRequest(BaseModel):
    name: str
    description: str = ""


class CreateItemRequest(BaseModel):
    key: str
    name: str = ""
    value_type: str = "uint"    # uint|float|string|text|log
    poll_class: str = "fast"    # fast|slow|inventory|lld
    interval_sec: int = 60
    store_history: bool = True
    store_trends: bool = True


class AssignTemplateRequest(BaseModel):
    template_id: int
    enabled: bool = True


class UpdateAgentStatusRequest(BaseModel):
    admin_status: str  # active|revoked|disabled


# ──────────────────────────────────────────────────────────────────────────────
# AGENTS
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/agents")
async def list_agents(
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all agents for tenant with computed online status."""
    result = await db.execute(
        select(Agent).where(Agent.tenant_id == tenant_id).order_by(Agent.created_at)
    )
    agents = result.scalars().all()
    now = int(time.time())
    return [_agent_dict(a, now) for a in agents]


@router.get("/agents/{agent_id}")
async def get_agent(
    agent_id: int,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    agent = await _fetch_agent(agent_id, tenant_id, db)
    # Count devices owned by this agent
    result = await db.execute(
        select(func.count()).where(
            AgentDevice.device_owner_agent_id == agent_id,
            AgentDevice.tenant_id == tenant_id,
        )
    )
    device_count = result.scalar_one()
    d = _agent_dict(agent, int(time.time()))
    d["device_count"] = device_count
    return d


@router.patch("/agents/{agent_id}/status")
async def update_agent_status(
    agent_id: int,
    body: UpdateAgentStatusRequest,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    if body.admin_status not in ("active", "revoked", "disabled"):
        raise HTTPException(status_code=400, detail="Invalid admin_status")
    agent = await _fetch_agent(agent_id, tenant_id, db)
    agent.admin_status = body.admin_status
    _audit(db, tenant_id, "update_agent_status", "agent", str(agent_id),
           {"admin_status": body.admin_status})
    await db.commit()
    return {"ok": True, "admin_status": agent.admin_status}


@router.post("/agents/{agent_id}/command")
async def issue_command(
    agent_id: int,
    body: IssueCommandRequest,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Issue a command to an agent (queued; agent picks up via MQTT or polling)."""
    await _fetch_agent(agent_id, tenant_id, db)
    command_id = str(uuid.uuid4())
    cmd = AgentCommand(
        tenant_id=tenant_id,
        agent_id=agent_id,
        command_id=command_id,
        command_type=body.command_type,
        issued_at=int(time.time()),
        issued_by=body.issued_by,
        payload=json.dumps(body.payload),
        status="pending",
    )
    db.add(cmd)
    _audit(db, tenant_id, "issue_command", "agent", str(agent_id),
           {"command_type": body.command_type, "command_id": command_id})
    await db.commit()

    # Publish to MQTT (non-blocking best-effort)
    await _publish_command_mqtt(agent_id, tenant_id, command_id, body)

    return {"command_id": command_id, "status": "pending"}


# ──────────────────────────────────────────────────────────────────────────────
# DEVICES
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/devices")
async def list_devices(
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List all devices with computed online and health_status."""
    result = await db.execute(
        select(AgentDevice).where(AgentDevice.tenant_id == tenant_id)
        .order_by(AgentDevice.created_at)
    )
    devices = result.scalars().all()
    now = int(time.time())
    out = []
    for dev in devices:
        # Compute health_status from active alerts
        health = await _compute_health(dev.id, db)
        active_count = await _active_alert_count(dev.id, db)
        out.append({
            "id": dev.id,
            "device_uid": dev.device_uid,
            "name": dev.name,
            "ip": dev.ip,
            "mac": dev.mac,
            "serial": dev.serial,
            "vendor": dev.vendor,
            "model": dev.model,
            "device_class": dev.device_class,
            "location": dev.location,
            "online": (now - dev.last_seen) < _ONLINE_THRESHOLD_DEVICE if dev.last_seen else False,
            "last_seen": dev.last_seen,
            "health_status": health,
            "active_alerts": active_count,
            "profile_id": dev.profile_id,
            "owner_agent_id": dev.device_owner_agent_id,
        })
    return out


@router.get("/devices/{device_id}")
async def get_device(
    device_id: int,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Device detail: header fields + inventory + last_values + active alerts."""
    dev = await _fetch_device(device_id, tenant_id, db)
    now = int(time.time())

    # Inventory
    inv = await db.get(DeviceInventory, device_id)
    inv_data = None
    if inv:
        inv_data = {
            "vendor": inv.vendor, "model": inv.model, "serial": inv.serial,
            "cpu_model": inv.cpu_model, "ram_gb": inv.ram_gb,
            "disk_count": inv.disk_count, "firmware_version": inv.firmware_version,
            "updated_at": str(inv.updated_at),
        }

    # Last values (top 50)
    lv_result = await db.execute(
        select(LastValue, Item.key, Item.name, Item.value_type)
        .join(Item, LastValue.item_id == Item.id)
        .where(LastValue.device_id == device_id)
        .order_by(desc(LastValue.clock))
        .limit(50)
    )
    last_values = [
        {"key": key, "name": name, "value": lv.value, "value_type": vt, "clock": lv.clock}
        for lv, key, name, vt in lv_result.all()
    ]

    # Active alerts
    alert_result = await db.execute(
        select(Alert).where(Alert.device_id == device_id, Alert.active.is_(True))
    )
    active_alerts = [_alert_dict(a) for a in alert_result.scalars().all()]

    health = await _compute_health(device_id, db)
    active_count = len(active_alerts)

    return {
        "id": dev.id,
        "device_uid": dev.device_uid,
        "name": dev.name,
        "ip": dev.ip,
        "mac": dev.mac,
        "serial": dev.serial,
        "vendor": dev.vendor,
        "model": dev.model,
        "device_class": dev.device_class,
        "location": dev.location,
        "online": (now - dev.last_seen) < _ONLINE_THRESHOLD_DEVICE if dev.last_seen else False,
        "last_seen": dev.last_seen,
        "health_status": health,
        "active_alerts": active_count,
        "profile_id": dev.profile_id,
        "owner_agent_id": dev.device_owner_agent_id,
        "inventory": inv_data,
        "last_values": last_values,
        "alerts": active_alerts,
    }


@router.get("/devices/{device_id}/history")
async def get_device_history(
    device_id: int,
    item_id: int,
    value_type: str = "float",
    from_ts: int = 0,
    to_ts: Optional[int] = None,
    limit: int = 500,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Return history values for a specific item on this device."""
    await _fetch_device(device_id, tenant_id, db)
    if to_ts is None:
        to_ts = int(time.time())

    hist_cls = HISTORY_TABLE_MAP.get(value_type)
    if not hist_cls:
        raise HTTPException(status_code=400, detail=f"Invalid value_type: {value_type}")

    result = await db.execute(
        select(hist_cls)
        .where(
            hist_cls.tenant_id == tenant_id,
            hist_cls.device_id == device_id,
            hist_cls.item_id == item_id,
            hist_cls.clock >= from_ts,
            hist_cls.clock <= to_ts,
        )
        .order_by(hist_cls.clock)
        .limit(limit)
    )
    rows = result.scalars().all()
    return [{"clock": r.clock, "value": r.value} for r in rows]


# ──────────────────────────────────────────────────────────────────────────────
# PROFILES + TEMPLATES + ITEMS
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/profiles")
async def list_profiles(
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Profile).where(Profile.tenant_id == tenant_id)
    )
    return [
        {"id": p.id, "name": p.name, "vendor": p.vendor, "version": p.version, "description": p.description}
        for p in result.scalars().all()
    ]


@router.post("/profiles", status_code=201)
async def create_profile(
    body: CreateProfileRequest,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    profile = Profile(
        tenant_id=tenant_id,
        name=body.name,
        vendor=body.vendor,
        version=body.version,
        description=body.description,
    )
    db.add(profile)
    _audit(db, tenant_id, "create_profile", "profile", "", {"name": body.name})
    await db.commit()
    await db.refresh(profile)
    return {"id": profile.id, "name": profile.name}


@router.get("/profiles/{profile_id}/templates")
async def list_templates(
    profile_id: int,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Template).where(Template.profile_id == profile_id, Template.tenant_id == tenant_id)
    )
    templates = result.scalars().all()
    out = []
    for tmpl in templates:
        item_result = await db.execute(select(Item).where(Item.template_id == tmpl.id))
        items = item_result.scalars().all()
        out.append({
            "id": tmpl.id,
            "name": tmpl.name,
            "description": tmpl.description,
            "items": [
                {"id": i.id, "key": i.key, "name": i.name, "value_type": i.value_type,
                 "poll_class": i.poll_class, "interval_sec": i.interval_sec}
                for i in items
            ],
        })
    return out


@router.post("/profiles/{profile_id}/templates", status_code=201)
async def create_template(
    profile_id: int,
    body: CreateTemplateRequest,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    tmpl = Template(
        tenant_id=tenant_id,
        profile_id=profile_id,
        name=body.name,
        description=body.description,
    )
    db.add(tmpl)
    _audit(db, tenant_id, "create_template", "template", "", {"name": body.name, "profile_id": profile_id})
    await db.commit()
    await db.refresh(tmpl)
    return {"id": tmpl.id, "name": tmpl.name}


@router.post("/templates/{template_id}/items", status_code=201)
async def create_item(
    template_id: int,
    body: CreateItemRequest,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Add item to template. MVP: app-level check for key uniqueness within profile.
    per portal_backend_tz.md K-2.
    """
    # Verify template belongs to tenant
    tmpl = await db.get(Template, template_id)
    if not tmpl or tmpl.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Template not found")

    # K-2: check key uniqueness within profile
    conflict = await db.execute(
        select(Item)
        .join(Template, Item.template_id == Template.id)
        .where(
            Template.profile_id == tmpl.profile_id,
            Item.key == body.key,
            Item.tenant_id == tenant_id,
        )
    )
    if conflict.scalar_one_or_none():
        raise HTTPException(status_code=409, detail=f"Key '{body.key}' already exists in this profile")

    item = Item(
        tenant_id=tenant_id,
        template_id=template_id,
        key=body.key,
        name=body.name,
        value_type=body.value_type,
        poll_class=body.poll_class,
        interval_sec=body.interval_sec,
        store_history=body.store_history,
        store_trends=body.store_trends,
    )
    db.add(item)
    _audit(db, tenant_id, "create_item", "item", "", {"key": body.key, "template_id": template_id})
    await db.commit()
    await db.refresh(item)
    return {"id": item.id, "key": item.key}


@router.post("/devices/{device_id}/templates", status_code=201)
async def assign_template(
    device_id: int,
    body: AssignTemplateRequest,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Assign a template to a device.
    Business rule K-3: template must belong to device's profile.
    """
    dev = await _fetch_device(device_id, tenant_id, db)
    tmpl = await db.get(Template, body.template_id)
    if not tmpl or tmpl.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Template not found")

    # K-3: template must belong to device's profile
    if dev.profile_id and tmpl.profile_id != dev.profile_id:
        raise HTTPException(
            status_code=409,
            detail=f"Template profile_id={tmpl.profile_id} does not match device profile_id={dev.profile_id}"
        )

    dt = DeviceTemplate(
        tenant_id=tenant_id,
        device_id=device_id,
        template_id=body.template_id,
        enabled=body.enabled,
    )
    db.add(dt)
    _audit(db, tenant_id, "assign_template", "device", str(device_id),
           {"template_id": body.template_id})
    await db.commit()
    return {"ok": True}


# ──────────────────────────────────────────────────────────────────────────────
# ZABBIX IMPORT
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/profiles/import/zabbix")
async def import_zabbix_template(
    file: UploadFile = File(...),
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a Zabbix template file (.xml, .json, .yaml/.yml) and
    convert it to a NOCKO SNMP profile with templates and items.
    Returns the created profile id and import summary.
    """
    MAX_SIZE = 5 * 1024 * 1024  # 5 MB
    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")

    try:
        parsed = parse_zabbix_template(content, file.filename or "template")
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse error: {e}")

    pdata = parsed.get("profile", {})
    templates_data = parsed.get("templates", [])
    warnings = parsed.get("warnings", [])

    if not pdata or not templates_data:
        raise HTTPException(
            status_code=422,
            detail=f"Nothing importable found. Warnings: {warnings[:5]}"
        )

    # Create the profile
    profile = Profile(
        tenant_id=tenant_id,
        name=pdata.get("name", "Imported Profile"),
        vendor=pdata.get("vendor", "Zabbix Import"),
        version=pdata.get("version", "1.0.0"),
        description=pdata.get("description", ""),
    )
    db.add(profile)
    await db.flush()  # get profile.id

    created_templates = 0
    created_items = 0
    skipped_items = 0

    for tmpl_data in templates_data:
        tmpl = Template(
            tenant_id=tenant_id,
            profile_id=profile.id,
            name=tmpl_data["name"],
            description=tmpl_data.get("description", ""),
        )
        db.add(tmpl)
        await db.flush()
        created_templates += 1

        seen_keys: set[str] = set()
        for item_data in tmpl_data.get("items", []):
            key = item_data["key"]
            if key in seen_keys:
                skipped_items += 1
                warnings.append(f"Duplicate key '{key}' in template '{tmpl_data['name']}' — skipped")
                continue
            seen_keys.add(key)

            item = Item(
                tenant_id=tenant_id,
                template_id=tmpl.id,
                key=key,
                name=item_data.get("name") or key,
                value_type=item_data.get("value_type", "uint"),
                poll_class=item_data.get("poll_class", "fast"),
                interval_sec=item_data.get("interval_sec", 60),
            )
            db.add(item)
            created_items += 1

    _audit(db, tenant_id, "import_zabbix", "profile", str(profile.id),
           {"filename": file.filename, "templates": created_templates, "items": created_items})
    await db.commit()

    return {
        "ok": True,
        "profile_id": profile.id,
        "profile_name": profile.name,
        "templates_created": created_templates,
        "items_created": created_items,
        "items_skipped": skipped_items,
        "warnings": warnings,
    }


# ──────────────────────────────────────────────────────────────────────────────
@router.get("/alerts")
async def list_alerts(
    active_only: bool = True,
    severity: Optional[str] = None,
    limit: int = 200,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List alerts for tenant. By default returns active only."""
    q = select(Alert).where(Alert.tenant_id == tenant_id)
    if active_only:
        q = q.where(Alert.active.is_(True))
    if severity:
        q = q.where(Alert.severity == severity)
    q = q.order_by(desc(Alert.opened_at)).limit(limit)
    result = await db.execute(q)
    return [_alert_dict(a) for a in result.scalars().all()]


@router.post("/alerts/{alert_id}/close")
async def close_alert(
    alert_id: int,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Manually close an alert (operator action). K-5b: sets active=false, closed_at=now."""
    alert = await db.get(Alert, alert_id)
    if not alert or alert.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    if not alert.active:
        return {"ok": True, "message": "Already closed"}

    now = int(time.time())
    alert.active = False
    alert.closed_at = now
    _audit(db, tenant_id, "close_alert", "alert", str(alert_id), {"manual": True})
    await db.commit()
    return {"ok": True, "closed_at": now}


# ──────────────────────────────────────────────────────────────────────────────
# EVENTS
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/devices/{device_id}/events")
async def get_device_events(
    device_id: int,
    limit: int = 100,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """Recent events for a device."""
    await _fetch_device(device_id, tenant_id, db)
    result = await db.execute(
        select(Event)
        .where(Event.device_id == device_id, Event.tenant_id == tenant_id)
        .order_by(desc(Event.clock))
        .limit(limit)
    )
    return [
        {
            "id": e.id, "event_type": e.event_type, "source": e.source,
            "severity": e.severity, "code": e.code, "message": e.message,
            "clock": e.clock,
        }
        for e in result.scalars().all()
    ]


# ──────────────────────────────────────────────────────────────────────────────
# COMMANDS STATUS
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/agents/{agent_id}/commands")
async def get_agent_commands(
    agent_id: int,
    limit: int = 50,
    tenant_id: int = Depends(_get_tenant_id),
    db: AsyncSession = Depends(get_db),
):
    """List recent commands for an agent."""
    await _fetch_agent(agent_id, tenant_id, db)
    result = await db.execute(
        select(AgentCommand)
        .where(AgentCommand.agent_id == agent_id, AgentCommand.tenant_id == tenant_id)
        .order_by(desc(AgentCommand.issued_at))
        .limit(limit)
    )
    cmds = result.scalars().all()
    return [
        {
            "command_id": c.command_id,
            "command_type": c.command_type,
            "status": c.status,
            "issued_at": c.issued_at,
            "issued_by": c.issued_by,
        }
        for c in cmds
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────
async def _fetch_agent(agent_id: int, tenant_id: int, db: AsyncSession) -> Agent:
    agent = await db.get(Agent, agent_id)
    if not agent or agent.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _fetch_device(device_id: int, tenant_id: int, db: AsyncSession) -> AgentDevice:
    dev = await db.get(AgentDevice, device_id)
    if not dev or dev.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Device not found")
    return dev


async def _compute_health(device_id: int, db: AsyncSession) -> str:
    """Compute health_status = max severity FROM active alerts. K-7."""
    result = await db.execute(
        select(Alert.severity)
        .where(Alert.device_id == device_id, Alert.active.is_(True))
    )
    severities = result.scalars().all()
    if "critical" in severities:
        return "critical"
    if "warning" in severities:
        return "warning"
    if severities:
        return "info"
    return "ok"


async def _active_alert_count(device_id: int, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.count()).where(Alert.device_id == device_id, Alert.active.is_(True))
    )
    return result.scalar_one()


def _agent_dict(a: Agent, now: int) -> dict:
    return {
        "id": a.id,
        "tenant_id": a.tenant_id,
        "name": a.name,
        "hostname": a.hostname,
        "ip": a.ip,
        "version": a.version,
        "admin_status": a.admin_status,
        "online": (now - a.last_seen) < _ONLINE_THRESHOLD_AGENT if a.last_seen else False,
        "last_seen": a.last_seen,
        "created_at": str(a.created_at),
    }


def _alert_dict(a: Alert) -> dict:
    return {
        "id": a.id,
        "device_id": a.device_id,
        "item_id": a.item_id,
        "severity": a.severity,
        "message": a.message,
        "source": a.source,
        "active": a.active,
        "opened_at": a.opened_at,
        "closed_at": a.closed_at,
    }


def _audit(db: AsyncSession, tenant_id: int, action: str, entity_type: str,
           entity_id: str, details: dict) -> None:
    db.add(AgentAuditLog(
        tenant_id=tenant_id,
        action=action,
        actor="portal",
        entity_type=entity_type,
        entity_id=entity_id,
        details=json.dumps(details),
    ))


async def _publish_command_mqtt(
    agent_id: int, tenant_id: int, command_id: str, body: IssueCommandRequest
) -> None:
    """Best-effort MQTT publish of command to agent."""
    try:
        from mqtt_publisher import MqttPublisher
        topic = f"nocko/{tenant_id}/{agent_id}/commands"
        payload = {
            "command_id": command_id,
            "command_type": body.command_type,
            "issued_at": int(time.time()),
            "issued_by": body.issued_by,
            "payload": body.payload,
        }
        await MqttPublisher.publish(topic, payload)
    except Exception:
        pass  # command is persisted in DB; agent will poll via /commands/pending
