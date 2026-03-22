"""
Agent API — endpoints called by the NOCKO Proxy Agent.
All routes are under /api/v1/agent/

Endpoints:
  POST  /api/v1/agent/register          ← Bootstrap: enroll with token
  POST  /api/v1/agent/unregister        ← Revoke agent (install.sh --uninstall)
  GET   /api/v1/agent/linux-bundle      ← Linux tarball URL + sha256 (public)
  GET   /api/v1/agent/bootstrap/install.sh ← One-liner installer script (public)
  GET   /api/v1/agent/config            ← Fetch server-managed config
  GET   /api/v1/agent/items             ← Fetch items for a profile
  POST  /api/v1/agent/ingest            ← Receive payload (metrics/inventory/events/heartbeat)
  POST  /api/v1/agent/command-result    ← Receive command execution result
  GET   /api/v1/agent/commands/pending  ← Fetch pending commands for agent

Auth: Bearer token (auth_token from registration).
"""
from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any, Optional

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Header, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert as pg_insert

from database import get_db
from package_builder.release_catalog import find_linux_proxy_bundle
from agent_models import (
    Agent, AgentDevice, Item, Template, DeviceTemplate, Profile,
    DeviceInventory, Event, Alert, AgentAuditLog, AgentCommand, AgentCommandResult,
    LastValue, HISTORY_TABLE_MAP,
)

router = APIRouter(prefix="/api/v1/agent", tags=["Agent API"])


def _mqtt_broker_url_for_agents() -> str:
    """
    Broker URL returned to agents during bootstrap.
    Agents run outside Docker — do not default to internal service names (e.g. emqx).

    Transports:
      - tcp MQTT:  mqtt://host:1883
      - WSS (same host/port as HTTPS, path e.g. /mqtt): wss://host:443/mqtt
    """
    import os

    if v := os.getenv("MQTT_BROKER_URL", "").strip():
        return v
    host = os.getenv("MQTT_PUBLIC_HOST", "").strip()
    if not host:
        mdm = (os.getenv("MDM_SERVER_URL", "") or "").replace("https://", "").replace("http://", "")
        host = mdm.strip().rstrip("/").split("/")[0] or "localhost"

    transport = (
        os.getenv("MQTT_PUBLIC_TRANSPORT", "").strip()
        or os.getenv("MQTT_TRANSPORT", "").strip()
        or "tcp"
    ).lower()

    # MQTT over WebSocket Secure — typically nginx :443 → broker (see nginx/mdm-mqtt.conf)
    if transport in ("websockets", "websocket", "wss", "ws"):
        path = (os.getenv("MQTT_PATH") or "/mqtt").strip()
        if not path.startswith("/"):
            path = "/" + path
        port = (os.getenv("MQTT_PUBLIC_WSS_PORT") or os.getenv("MQTT_WSS_PORT") or "443").strip()
        if port == "443":
            return f"wss://{host}{path}"
        return f"wss://{host}:{port}{path}"

    port = os.getenv("MQTT_PUBLIC_PORT", "1883").strip()
    return f"mqtt://{host}:{port}"


# ─── Auth helper ──────────────────────────────────────────────────────────────

async def _get_agent(
    authorization: str = Header(...),
    db: AsyncSession = Depends(get_db),
) -> Agent:
    """Validate Bearer token and return Agent row."""
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing Bearer token")
    token = authorization.removeprefix("Bearer ").strip()
    result = await db.execute(select(Agent).where(Agent.auth_token == token))
    agent = result.scalar_one_or_none()
    if not agent or agent.admin_status != "active":
        raise HTTPException(status_code=401, detail="Invalid or revoked agent token")
    return agent


# ──────────────────────────────────────────────────────────────────────────────
# Pydantic schemas
# ──────────────────────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    enrollment_token: str
    hostname: str = ""
    version: str = "1.0.0"
    ip: str = ""


class IngestEnvelope(BaseModel):
    schema_version: str = "1.0"
    tenant_id: int
    agent_id: int
    sent_at: int
    payload_type: str  # metrics.fast | metrics.slow | inventory | events | heartbeat
    records: list[dict]


class CommandResultRequest(BaseModel):
    command_id: str
    status: str           # done | failed
    result: str = ""
    error_message: Optional[str] = None
    finished_at: int


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/agent/register
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/register")
async def register_agent(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """
    Bootstrap: enroll proxy agent using one-time enrollment token.
    Token is validated against enrollment_tokens table (existing Windows MDM table).
    Returns: agent_id, tenant_id, auth_token, broker_url.
    """
    from models import EnrollmentToken, Customer

    # Validate enrollment token
    result = await db.execute(
        select(EnrollmentToken).where(
            EnrollmentToken.token == body.enrollment_token,
            EnrollmentToken.revoked.is_(False)
        )
    )
    token_row = result.scalar_one_or_none()
    if not token_row:
        raise HTTPException(status_code=403, detail="Invalid or revoked enrollment token")

    # Get or create Tenant for this customer
    from agent_models import Tenant
    tenant_result = await db.execute(
        select(Tenant).where(Tenant.customer_id == token_row.customer_id)
    )
    tenant = tenant_result.scalar_one_or_none()
    if not tenant:
        customer_result = await db.execute(
            select(Customer).where(Customer.id == token_row.customer_id)
        )
        customer = customer_result.scalar_one_or_none()
        tenant = Tenant(
            name=customer.name if customer else f"tenant_{token_row.customer_id}",
            customer_id=token_row.customer_id,
        )
        db.add(tenant)
        await db.flush()

    # Create agent
    auth_token = f"agt_{uuid.uuid4().hex}"
    agent = Agent(
        tenant_id=tenant.id,
        name=body.hostname or "unknown",
        version=body.version,
        ip=body.ip,
        hostname=body.hostname,
        admin_status="active",
        auth_token=auth_token,
        last_seen=int(time.time()),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)

    broker_url = _mqtt_broker_url_for_agents()

    return {
        "agent_id": agent.id,
        "tenant_id": tenant.id,
        "auth_token": auth_token,
        "broker_url": broker_url,
        "config_version": "1.0",
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/linux-bundle  (public — bootstrap installer)
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/linux-bundle")
async def linux_proxy_bundle():
    """
    Metadata for the Linux proxy-agent tarball from the release catalog.
    install.sh verifies sha256 before extract (integrity per TZ §5.3).
    """
    release, art = find_linux_proxy_bundle()
    if not release or not art:
        raise HTTPException(
            status_code=404,
            detail="No linux-tarball (linux-tarball / amd64) in agent release catalog",
        )
    sha = (art.get("sha256") or "").strip()
    if not sha:
        raise HTTPException(
            status_code=503,
            detail="Linux bundle in catalog has no sha256 — fix release publishing",
        )
    url = (art.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=503, detail="Linux bundle has no download url")
    return {
        "version": str(release.get("version", "")),
        "tag": release.get("tag"),
        "filename": art.get("filename"),
        "url": url,
        "sha256": sha,
        "size_bytes": art.get("size_bytes"),
        "signature_url": art.get("signature_url"),  # optional detached sig (e.g. .minisig)
    }


def _public_mdm_base(request: Request) -> str:
    xf = (request.headers.get("x-forwarded-proto") or "").strip()
    host = (request.headers.get("x-forwarded-host") or request.headers.get("host") or "").strip()
    if xf and host:
        return f"{xf}://{host}".rstrip("/")
    return str(request.base_url).rstrip("/")


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/bootstrap/install.sh  (public — one-liner from TZ §5)
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/bootstrap/install.sh")
async def bootstrap_install_script(request: Request):
    """
    Full install.sh with NOCKO_MDM_BASE injected (from Host / X-Forwarded-*).
    Usage: curl -fsSL https://<mdm>/api/v1/agent/bootstrap/install.sh | sudo bash -s -- '<token>'
    """
    base = _public_mdm_base(request)
    path = Path(__file__).resolve().parent.parent / "agent_bootstrap" / "install-proxy-agent.sh"
    if not path.is_file():
        raise HTTPException(
            status_code=500,
            detail="install-proxy-agent.sh not found — rebuild backend image with proxy-agent/install.sh",
        )
    body = path.read_text(encoding="utf-8")
    inject = f"export NOCKO_MDM_BASE={json.dumps(base)}\n"
    if body.startswith("#!"):
        nl = body.find("\n")
        if nl != -1:
            body = body[: nl + 1] + inject + body[nl + 1 :]
        else:
            body = inject + body
    else:
        body = inject + body
    return Response(content=body, media_type="text/plain; charset=utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/agent/unregister  (Bearer — TZ §5.4)
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/unregister")
async def unregister_agent(
    agent: Agent = Depends(_get_agent),
    db: AsyncSession = Depends(get_db),
):
    """Revoke agent token; used by install.sh --uninstall."""
    agent.admin_status = "revoked"
    await db.commit()
    return {"ok": True, "agent_id": agent.id}


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/config
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/config")
async def get_agent_config(agent: Agent = Depends(_get_agent)):
    """Return server-managed configuration for this agent."""
    import os
    return {
        "agent_id": agent.id,
        "tenant_id": agent.tenant_id,
        "config_version": "1.0",
        "heartbeat_interval": int(os.getenv("AGENT_HEARTBEAT_INTERVAL", 60)),
        "metrics_fast_interval": int(os.getenv("AGENT_FAST_INTERVAL", 60)),
        "metrics_slow_interval": int(os.getenv("AGENT_SLOW_INTERVAL", 300)),
        "inventory_interval": int(os.getenv("AGENT_INVENTORY_INTERVAL", 86400)),
        "broker_url": _mqtt_broker_url_for_agents(),
        "broker_port": int(os.getenv("MQTT_BROKER_PORT", 8883)),
    }


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/items?profile_id=X
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/items")
async def get_items(
    profile_id: int,
    agent: Agent = Depends(_get_agent),
    db: AsyncSession = Depends(get_db),
):
    """Return all items for a profile (flat list with output_mapping fields)."""
    result = await db.execute(
        select(Item, Template.profile_id)
        .join(Template, Item.template_id == Template.id)
        .where(
            Template.profile_id == profile_id,
            Item.tenant_id == agent.tenant_id,
        )
    )
    rows = result.all()
    return [
        {
            "item_id": item.id,
            "key": item.key,
            "name": item.name,
            "value_type": item.value_type,
            "poll_class": item.poll_class,
            "interval_sec": item.interval_sec,
            "store_history": item.store_history,
        }
        for item, _ in rows
    ]


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/agent/ingest
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/ingest", status_code=202)
async def ingest(
    body: IngestEnvelope,
    agent: Agent = Depends(_get_agent),
    db: AsyncSession = Depends(get_db),
):
    """
    Main data ingestion endpoint. Accepts all payload types.
    Dispatches to dedicated handlers based on payload_type.
    """
    # Update agent last_seen
    await db.execute(
        update(Agent).where(Agent.id == agent.id).values(last_seen=int(time.time()))
    )

    ptype = body.payload_type
    errors: list[str] = []

    if ptype in ("metrics.fast", "metrics.slow", "metrics"):
        for record in body.records:
            errs = await _ingest_metrics(record, agent, db)
            errors.extend(errs)

    elif ptype == "inventory":
        for record in body.records:
            await _ingest_inventory(record, agent, db)

    elif ptype == "events":
        for record in body.records:
            errs = await _ingest_event(record, agent, db)
            errors.extend(errs)

    elif ptype == "heartbeat":
        # last_seen already updated above; nothing more needed
        pass

    else:
        raise HTTPException(status_code=422, detail=f"Unknown payload_type: {ptype}")

    await db.commit()
    return {"accepted": True, "warnings": errors[:20]}  # cap warning list


# ──────────────────────────────────────────────────────────────────────────────
# Ingest: metrics
# ──────────────────────────────────────────────────────────────────────────────
async def _ingest_metrics(record: dict, agent: Agent, db: AsyncSession) -> list[str]:
    """Process one record from a metrics payload."""
    warnings: list[str] = []
    tid = agent.tenant_id

    # Step 1: Resolve device_uid → device.id
    device_uid = record.get("device_uid", "")
    device = await _resolve_device(device_uid, tid, agent.id, db)
    if not device:
        warnings.append(f"device_uid not found: {device_uid}")
        return warnings

    clock = record.get("clock", int(time.time()))
    enqueue_ts = record.get("enqueue_ts", clock)
    data: dict[str, Any] = record.get("data", {})

    for key, raw_value in data.items():
        # Step 2: Resolve key → item via device_templates (enabled=true only)
        item = await _resolve_item(key, device.id, tid, db)
        if item is None:
            warnings.append(f"key not found or conflict: {key} for device {device_uid}")
            continue

        # Step 3: Type validation
        typed_value, ok = _cast_value(raw_value, item.value_type)
        if not ok:
            warnings.append(f"type_mismatch: key={key} expected={item.value_type} got={type(raw_value).__name__}")
            continue

        # Step 4: Insert into history_{value_type}
        if item.store_history:
            hist_cls = HISTORY_TABLE_MAP.get(item.value_type)
            if hist_cls:
                db.add(hist_cls(
                    tenant_id=tid,
                    device_id=device.id,
                    item_id=item.id,
                    agent_id=agent.id,
                    clock=clock,
                    enqueue_ts=enqueue_ts,
                    value=typed_value,
                ))

        # Step 5: Upsert last_values
        lv = await db.get(LastValue, (device.id, item.id))
        if lv:
            lv.value = str(typed_value)
            lv.clock = clock
            lv.agent_id = agent.id
        else:
            db.add(LastValue(
                device_id=device.id,
                item_id=item.id,
                tenant_id=tid,
                agent_id=agent.id,
                value=str(typed_value),
                clock=clock,
            ))

    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# Ingest: inventory
# ──────────────────────────────────────────────────────────────────────────────
async def _ingest_inventory(record: dict, agent: Agent, db: AsyncSession) -> None:
    """Upsert inventory snapshot for a device."""
    tid = agent.tenant_id
    device_uid = record.get("device_uid", "")
    device = await _resolve_device(device_uid, tid, agent.id, db)
    if not device:
        return

    data: dict = record.get("data", {})
    inv = await db.get(DeviceInventory, device.id)
    if inv:
        inv.vendor = data.get("vendor", inv.vendor)
        inv.model = data.get("model", inv.model)
        inv.serial = data.get("serial", inv.serial)
        inv.cpu_model = data.get("cpu_model", inv.cpu_model)
        inv.ram_gb = data.get("ram_gb", inv.ram_gb)
        inv.disk_count = data.get("disk_count", inv.disk_count)
        inv.firmware_version = data.get("firmware_version", inv.firmware_version)
        inv.data_json = json.dumps(data)
        inv.last_agent_id = agent.id
    else:
        db.add(DeviceInventory(
            device_id=device.id,
            tenant_id=tid,
            last_agent_id=agent.id,
            vendor=data.get("vendor", ""),
            model=data.get("model", ""),
            serial=data.get("serial", ""),
            cpu_model=data.get("cpu_model", ""),
            ram_gb=data.get("ram_gb"),
            disk_count=data.get("disk_count"),
            firmware_version=data.get("firmware_version", ""),
            data_json=json.dumps(data),
        ))

    # Sync top-level fields to agent_devices for list view
    device.vendor = data.get("vendor", device.vendor)
    device.model = data.get("model", device.model)
    device.serial = data.get("serial", device.serial)


# ──────────────────────────────────────────────────────────────────────────────
# Ingest: events
# ──────────────────────────────────────────────────────────────────────────────
async def _ingest_event(record: dict, agent: Agent, db: AsyncSession) -> list[str]:
    """Insert event with dedup_key guard. Open/close alerts as needed."""
    warnings: list[str] = []
    tid = agent.tenant_id
    device_uid = record.get("device_uid", "")
    device = await _resolve_device(device_uid, tid, agent.id, db)
    if not device:
        warnings.append(f"device_uid not found: {device_uid}")
        return warnings

    clock = record.get("clock", int(time.time()))
    event_type = record.get("event_type", "agent")
    source = record.get("source", "")
    severity = record.get("severity", "info")
    code = record.get("code", "")
    message = record.get("message", "")
    item_key = record.get("item_key")

    # Resolve item_key → item_id (optional)
    item_id: Optional[int] = None
    if item_key:
        item = await _resolve_item(item_key, device.id, tid, db)
        item_id = item.id if item else None

    # Dedup key
    dedup = Event.make_dedup_key(tid, device.id, event_type, source, code, clock)

    # ON CONFLICT DO NOTHING (via try/except for portability)
    existing = await db.execute(
        select(Event).where(Event.tenant_id == tid, Event.dedup_key == dedup)
    )
    if existing.scalar_one_or_none():
        return warnings  # duplicate, skip silently

    db.add(Event(
        tenant_id=tid,
        device_id=device.id,
        item_id=item_id,
        agent_id=agent.id,
        event_type=event_type,
        source=source,
        severity=severity,
        code=code,
        message=message,
        dedup_key=dedup,
        clock=clock,
    ))

    # Alert lifecycle
    if severity in ("warning", "critical"):
        await _open_alert(device.id, item_id, severity, message, source, clock, tid, db)
    elif severity == "ok":
        await _close_alert(device.id, item_id, clock, db)

    # Update device last_seen
    device.last_seen = clock
    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# POST /api/v1/agent/command-result
# ──────────────────────────────────────────────────────────────────────────────
@router.post("/command-result", status_code=202)
async def receive_command_result(
    body: CommandResultRequest,
    agent: Agent = Depends(_get_agent),
    db: AsyncSession = Depends(get_db),
):
    """Receive command execution result from agent."""
    db.add(AgentCommandResult(
        command_id=body.command_id,
        tenant_id=agent.tenant_id,
        agent_id=agent.id,
        status=body.status,
        result=body.result,
        error_message=body.error_message,
        finished_at=body.finished_at,
    ))
    # Update command status
    await db.execute(
        update(AgentCommand)
        .where(AgentCommand.command_id == body.command_id)
        .values(status=body.status)
    )
    await db.commit()
    return {"accepted": True}


# ──────────────────────────────────────────────────────────────────────────────
# GET /api/v1/agent/commands/pending
# ──────────────────────────────────────────────────────────────────────────────
@router.get("/commands/pending")
async def get_pending_commands(
    agent: Agent = Depends(_get_agent),
    db: AsyncSession = Depends(get_db),
):
    """Return pending commands for this agent."""
    result = await db.execute(
        select(AgentCommand).where(
            AgentCommand.agent_id == agent.id,
            AgentCommand.status == "pending",
        ).order_by(AgentCommand.issued_at)
    )
    cmds = result.scalars().all()
    return [
        {
            "command_id": c.command_id,
            "command_type": c.command_type,
            "issued_at": c.issued_at,
            "issued_by": c.issued_by,
            "payload": json.loads(c.payload),
        }
        for c in cmds
    ]


# ──────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────────────
_device_cache: dict[tuple, int] = {}  # (tenant_id, device_uid) → device.id
_item_cache: dict[tuple, Optional[int]] = {}  # (device_id, key) → item.id


async def _resolve_device(
    device_uid: str, tenant_id: int, agent_id: int, db: AsyncSession
) -> Optional[AgentDevice]:
    """Resolve device_uid → AgentDevice. Creates device if not found."""
    cache_key = (tenant_id, device_uid)
    cached_id = _device_cache.get(cache_key)
    if cached_id:
        return await db.get(AgentDevice, cached_id)

    result = await db.execute(
        select(AgentDevice).where(
            AgentDevice.tenant_id == tenant_id,
            AgentDevice.device_uid == device_uid,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        # Auto-register device (first seen)
        device = AgentDevice(
            device_uid=device_uid,
            tenant_id=tenant_id,
            device_owner_agent_id=agent_id,
            name=device_uid,
            last_seen=int(time.time()),
        )
        db.add(device)
        await db.flush()

    _device_cache[cache_key] = device.id
    return device


async def _resolve_item(
    key: str, device_id: int, tenant_id: int, db: AsyncSession
) -> Optional[Item]:
    """
    Resolve key → Item via device_templates (enabled=true only).
    Returns None if 0 or >1 results (logged as warning by caller).
    Caches (device_id, key) → item.id in memory.
    """
    cache_key = (device_id, key)
    if cache_key in _item_cache:
        cached_id = _item_cache[cache_key]
        if cached_id is None:
            return None
        return await db.get(Item, cached_id)

    result = await db.execute(
        select(Item)
        .join(DeviceTemplate, DeviceTemplate.template_id == Item.template_id)
        .where(
            DeviceTemplate.device_id == device_id,
            DeviceTemplate.enabled.is_(True),
            DeviceTemplate.tenant_id == tenant_id,
            Item.key == key,
        )
    )
    items = result.scalars().all()

    if len(items) == 1:
        _item_cache[cache_key] = items[0].id
        return items[0]

    _item_cache[cache_key] = None  # 0 or conflict
    return None


def _cast_value(raw: Any, value_type: str) -> tuple[Any, bool]:
    """Cast raw JSON value to the expected Python type. Returns (value, ok)."""
    try:
        if value_type in ("uint",):
            return int(raw), True
        elif value_type == "float":
            return float(raw), True
        elif value_type in ("string",):
            s = str(raw)
            return s[:255], True
        elif value_type in ("text", "log"):
            return str(raw), True
    except (TypeError, ValueError):
        pass
    return None, False


async def _open_alert(
    device_id: int, item_id: Optional[int], severity: str,
    message: str, source: str, clock: int, tenant_id: int, db: AsyncSession
) -> None:
    """Open a new alert if no active one exists for (device_id, item_id, source)."""
    q = select(Alert).where(
        Alert.device_id == device_id,
        Alert.active.is_(True),
        Alert.source == source,
    )
    if item_id is not None:
        q = q.where(Alert.item_id == item_id)
    existing = (await db.execute(q)).scalar_one_or_none()
    if not existing:
        db.add(Alert(
            tenant_id=tenant_id,
            device_id=device_id,
            item_id=item_id,
            severity=severity,
            message=message,
            source=source,
            active=True,
            opened_at=clock,
        ))


async def _close_alert(
    device_id: int, item_id: Optional[int], clock: int, db: AsyncSession
) -> None:
    """Close all active alerts for (device_id, item_id)."""
    q = update(Alert).where(
        Alert.device_id == device_id,
        Alert.active.is_(True),
    ).values(active=False, closed_at=clock)
    if item_id is not None:
        q = q.where(Alert.item_id == item_id)
    await db.execute(q)
