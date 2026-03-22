"""
Shared ingest logic — extracted from agent_router.py for reuse by:
  - REST endpoint: POST /api/v1/agent/ingest
  - MQTT consumer:  mqtt_consumer.py → _dispatch()

This module owns the full "envelope → DB" pipeline.
"""
from __future__ import annotations

import json
import time
from typing import Any, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from agent_models import (
    Agent, AgentDevice, Item, Template, DeviceTemplate, DeviceInventory,
    Event, Alert, LastValue, HISTORY_TABLE_MAP,
)


# ─── In-memory lookup caches (process-level, reset on restart) ────────────────
_device_cache: dict[tuple, int] = {}           # (tenant_id, device_uid) → id
_item_cache: dict[tuple, Optional[int]] = {}   # (device_id, key) → item_id | None


def invalidate_caches() -> None:
    """Call after reload_config or device_templates change."""
    _device_cache.clear()
    _item_cache.clear()


# ──────────────────────────────────────────────────────────────────────────────
# Main entry
# ──────────────────────────────────────────────────────────────────────────────
async def process_envelope(payload: dict, db: AsyncSession) -> list[str]:
    """
    Process one ingest envelope (metrics / inventory / events / heartbeat).
    Returns a list of warning strings.
    """
    # Locate agent by tenant_id + agent_id from envelope
    tenant_id = int(payload.get("tenant_id", 0))
    agent_id_raw = payload.get("agent_id")
    if not tenant_id or not agent_id_raw:
        return ["Missing tenant_id or agent_id in envelope"]

    result = await db.execute(
        select(Agent).where(Agent.id == int(agent_id_raw), Agent.tenant_id == tenant_id)
    )
    agent = result.scalar_one_or_none()
    if not agent or agent.admin_status != "active":
        return [f"Unknown or inactive agent: tenant={tenant_id} agent={agent_id_raw}"]

    # Update heartbeat
    await db.execute(
        update(Agent).where(Agent.id == agent.id).values(last_seen=int(time.time()))
    )

    ptype = payload.get("payload_type", "")
    records = payload.get("records", [])
    warnings: list[str] = []

    for record in records:
        if ptype in ("metrics.fast", "metrics.slow", "metrics"):
            warnings.extend(await _ingest_metrics(record, agent, db))
        elif ptype == "inventory":
            await _ingest_inventory(record, agent, db)
        elif ptype == "events":
            warnings.extend(await _ingest_event(record, agent, db))
        elif ptype in ("heartbeat", "agent_presence"):
            pass  # last_seen updated above
        else:
            warnings.append(f"Unknown payload_type: {ptype}")

    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# Metrics
# ──────────────────────────────────────────────────────────────────────────────
async def _ingest_metrics(record: dict, agent: Agent, db: AsyncSession) -> list[str]:
    warnings: list[str] = []
    tid = agent.tenant_id
    device_uid = record.get("device_uid", "")
    device = await _resolve_device(device_uid, tid, agent.id, db)
    if not device:
        warnings.append(f"device_uid not found: {device_uid}")
        return warnings

    clock = record.get("clock", int(time.time()))
    enqueue_ts = record.get("enqueue_ts", clock)
    data: dict[str, Any] = record.get("data", {})

    for key, raw_value in data.items():
        item = await _resolve_item(key, device.id, tid, db)
        if item is None:
            warnings.append(f"key not found or ambiguous: {key}")
            continue

        typed_value, ok = _cast(raw_value, item.value_type)
        if not ok:
            warnings.append(f"type_mismatch: key={key} expected={item.value_type}")
            continue

        if item.store_history:
            hist_cls = HISTORY_TABLE_MAP.get(item.value_type)
            if hist_cls:
                db.add(hist_cls(
                    tenant_id=tid, device_id=device.id, item_id=item.id,
                    agent_id=agent.id, clock=clock, enqueue_ts=enqueue_ts,
                    value=typed_value,
                ))

        # Upsert last_values
        lv = await db.get(LastValue, (device.id, item.id))
        if lv:
            lv.value = str(typed_value)
            lv.clock = clock
            lv.agent_id = agent.id
        else:
            db.add(LastValue(
                device_id=device.id, item_id=item.id, tenant_id=tid,
                agent_id=agent.id, value=str(typed_value), clock=clock,
            ))
    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# Inventory
# ──────────────────────────────────────────────────────────────────────────────
async def _ingest_inventory(record: dict, agent: Agent, db: AsyncSession) -> None:
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
            device_id=device.id, tenant_id=tid, last_agent_id=agent.id,
            vendor=data.get("vendor", ""), model=data.get("model", ""),
            serial=data.get("serial", ""), cpu_model=data.get("cpu_model", ""),
            ram_gb=data.get("ram_gb"), disk_count=data.get("disk_count"),
            firmware_version=data.get("firmware_version", ""),
            data_json=json.dumps(data),
        ))
    device.vendor = data.get("vendor", device.vendor)
    device.model = data.get("model", device.model)
    device.serial = data.get("serial", device.serial)


# ──────────────────────────────────────────────────────────────────────────────
# Events
# ──────────────────────────────────────────────────────────────────────────────
async def _ingest_event(record: dict, agent: Agent, db: AsyncSession) -> list[str]:
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

    item_id: Optional[int] = None
    if item_key:
        item = await _resolve_item(item_key, device.id, tid, db)
        item_id = item.id if item else None

    dedup = Event.make_dedup_key(tid, device.id, event_type, source, code, clock)
    existing = await db.execute(
        select(Event).where(Event.tenant_id == tid, Event.dedup_key == dedup)
    )
    if existing.scalar_one_or_none():
        return warnings  # duplicate

    db.add(Event(
        tenant_id=tid, device_id=device.id, item_id=item_id, agent_id=agent.id,
        event_type=event_type, source=source, severity=severity,
        code=code, message=message, dedup_key=dedup, clock=clock,
    ))

    if severity in ("warning", "critical"):
        await _open_alert(device.id, item_id, severity, message, source, clock, tid, db)
    elif severity == "ok":
        await _close_alert(device.id, item_id, clock, db)

    device.last_seen = clock
    return warnings


# ──────────────────────────────────────────────────────────────────────────────
# Alert lifecycle helpers
# ──────────────────────────────────────────────────────────────────────────────
async def _open_alert(
    device_id: int, item_id: Optional[int], severity: str,
    message: str, source: str, clock: int, tenant_id: int, db: AsyncSession
) -> None:
    q = select(Alert).where(Alert.device_id == device_id, Alert.active.is_(True), Alert.source == source)
    if item_id is not None:
        q = q.where(Alert.item_id == item_id)
    if not (await db.execute(q)).scalar_one_or_none():
        db.add(Alert(
            tenant_id=tenant_id, device_id=device_id, item_id=item_id,
            severity=severity, message=message, source=source,
            active=True, opened_at=clock,
        ))


async def _close_alert(device_id: int, item_id: Optional[int], clock: int, db: AsyncSession) -> None:
    q = update(Alert).where(Alert.device_id == device_id, Alert.active.is_(True)
                             ).values(active=False, closed_at=clock)
    if item_id is not None:
        q = q.where(Alert.item_id == item_id)
    await db.execute(q)


# ──────────────────────────────────────────────────────────────────────────────
# Lookup helpers
# ──────────────────────────────────────────────────────────────────────────────
async def _resolve_device(
    device_uid: str, tenant_id: int, agent_id: int, db: AsyncSession
) -> Optional[AgentDevice]:
    ck = (tenant_id, device_uid)
    if ck in _device_cache:
        return await db.get(AgentDevice, _device_cache[ck])

    result = await db.execute(
        select(AgentDevice).where(AgentDevice.tenant_id == tenant_id, AgentDevice.device_uid == device_uid)
    )
    device = result.scalar_one_or_none()
    if not device:
        device = AgentDevice(
            device_uid=device_uid, tenant_id=tenant_id,
            device_owner_agent_id=agent_id, name=device_uid,
            last_seen=int(time.time()),
        )
        db.add(device)
        await db.flush()
    _device_cache[ck] = device.id
    return device


async def _resolve_item(key: str, device_id: int, tenant_id: int, db: AsyncSession) -> Optional[Item]:
    ck = (device_id, key)
    if ck in _item_cache:
        iid = _item_cache[ck]
        return await db.get(Item, iid) if iid else None

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
        _item_cache[ck] = items[0].id
        return items[0]
    _item_cache[ck] = None
    return None


def _cast(raw: Any, value_type: str) -> tuple[Any, bool]:
    try:
        if value_type == "uint":
            return int(raw), True
        elif value_type == "float":
            return float(raw), True
        elif value_type == "string":
            return str(raw)[:255], True
        elif value_type in ("text", "log"):
            return str(raw), True
    except (TypeError, ValueError):
        pass
    return None, False
