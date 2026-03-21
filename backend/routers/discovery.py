"""Proxy Agent discovery and ingestion router."""
from __future__ import annotations

import asyncio
import json
import secrets
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import (
    AssetAlert,
    AssetComponent,
    AssetHealth,
    AssetInventory,
    Customer,
    DiscoveredAsset,
    ProxyAgent,
    ProxyAgentCommand,
)
from mqtt_publisher import publish_proxy_command as _mqtt_publish_proxy
from schemas import (
    AssetHealthOut,
    AssetInventoryOut,
    DiscoveredAssetOut,
    DiscoveryIngestOut,
    DiscoveryIngestRequest,
    ProxyAgentCommandCreate,
    ProxyAgentCommandOut,
    ProxyAgentCreate,
    ProxyAgentOut,
)

router = APIRouter(prefix="/api/v1/discovery", tags=["discovery"])

_ASSET_QUERY_OPTIONS = (
    selectinload(DiscoveredAsset.inventory),
    selectinload(DiscoveredAsset.components),
    selectinload(DiscoveredAsset.health),
    selectinload(DiscoveredAsset.alerts),
)


def _new_proxy_token() -> str:
    return "proxy-" + secrets.token_urlsafe(18)


async def _resolve_customer(customer_id: str, db: AsyncSession) -> Customer:
    result = await db.execute(
        select(Customer).where(
            (Customer.id == customer_id) | (Customer.slug == customer_id)
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")
    return customer


def _split_capabilities(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def _effective_agent_status(agent: ProxyAgent) -> str:
    if not getattr(agent, "is_registered", False):
        return "Not registered"
    if not agent.last_checkin:
        return "Registered"
    age_s = (datetime.utcnow() - agent.last_checkin).total_seconds()
    return "Online" if age_s <= 900 else "Offline"


def _load_json_object(value: str | None) -> dict[str, Any]:
    try:
        payload = json.loads(value or "{}")
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def _iso_or_blank(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    return str(value or "").strip()


def _alert_identity_parts(
    source: str,
    code: str,
    message: str,
    extra_json: dict[str, Any],
    first_seen_at: datetime | None,
    last_seen_at: datetime | None,
) -> str:
    record_id = str(extra_json.get("record_id", "") or "").strip()
    if record_id:
        return "|".join([source.strip(), code.strip(), f"record:{record_id}"])
    event_time = str(extra_json.get("event_time", "") or "").strip()
    if event_time:
        return "|".join([source.strip(), code.strip(), event_time, message.strip()])
    first_seen = _iso_or_blank(first_seen_at)
    if first_seen:
        return "|".join([source.strip(), code.strip(), first_seen, message.strip()])
    last_seen = _iso_or_blank(last_seen_at)
    return "|".join([source.strip(), code.strip(), last_seen, message.strip()])


def _alert_identity_from_model(alert: AssetAlert) -> str:
    extra_json = _load_json_object(alert.extra_json)
    return _alert_identity_parts(
        source=alert.source,
        code=alert.code,
        message=alert.message,
        extra_json=extra_json,
        first_seen_at=alert.first_seen_at,
        last_seen_at=alert.last_seen_at,
    )


def _alert_identity_from_payload(alert: Any) -> str:
    extra_json = alert.extra_json if isinstance(alert.extra_json, dict) else {}
    return _alert_identity_parts(
        source=alert.source,
        code=alert.code,
        message=alert.message,
        extra_json=extra_json,
        first_seen_at=alert.first_seen_at,
        last_seen_at=alert.last_seen_at,
    )


def _alert_has_event_history(extra_json: dict[str, Any]) -> bool:
    return bool(extra_json.get("history_entry")) or bool(extra_json.get("event_time")) or bool(extra_json.get("record_id"))


def _alert_sort_value(alert_row: dict[str, Any]) -> tuple[int, str]:
    extra_json = alert_row.get("extra_json", {})
    if not isinstance(extra_json, dict):
        extra_json = {}
    event_time = str(extra_json.get("event_time", "") or "").strip()
    last_seen = _iso_or_blank(alert_row.get("last_seen_at"))
    first_seen = _iso_or_blank(alert_row.get("first_seen_at"))
    history_rank = 1 if event_time else 0
    return (history_rank, event_time or last_seen or first_seen)


def _serialize_agent(agent: ProxyAgent) -> ProxyAgentOut:
    return ProxyAgentOut(
        id=agent.id,
        customer_id=agent.customer_id,
        name=agent.name,
        site_name=agent.site_name,
        hostname=agent.hostname,
        ip_address=agent.ip_address,
        mac_address=agent.mac_address,
        portal_url=agent.portal_url,
        version=agent.version,
        status=_effective_agent_status(agent),
        is_registered=agent.is_registered,
        capabilities=_split_capabilities(agent.capabilities),
        auth_token=agent.auth_token,
        last_checkin=agent.last_checkin,
        registered_at=agent.registered_at,
        created_at=agent.created_at,
    )


def _serialize_asset(asset: DiscoveredAsset) -> DiscoveredAssetOut:
    try:
        raw_facts = json.loads(asset.raw_facts or "{}")
        if not isinstance(raw_facts, dict):
            raw_facts = {}
    except Exception:
        raw_facts = {}

    inventory = None
    if asset.inventory:
        try:
            inventory = AssetInventoryOut.model_validate(asset.inventory)
        except Exception:
            inventory = None

    components = []
    for component in asset.components:
        try:
            extra_json = json.loads(component.extra_json or "{}")
            if not isinstance(extra_json, dict):
                extra_json = {}
        except Exception:
            extra_json = {}
        components.append(
            {
                "id": component.id,
                "component_type": component.component_type,
                "name": component.name,
                "slot": component.slot,
                "model": component.model,
                "manufacturer": component.manufacturer,
                "serial_number": component.serial_number,
                "firmware_version": component.firmware_version,
                "capacity_gb": component.capacity_gb,
                "status": component.status,
                "health": component.health,
                "extra_json": extra_json,
            }
        )

    health = None
    if asset.health:
        try:
            health = AssetHealthOut.model_validate(asset.health)
        except Exception:
            health = None

    alerts = []
    for alert in asset.alerts:
        extra_json = _load_json_object(alert.extra_json)
        alerts.append(
            {
                "id": alert.id,
                "source": alert.source,
                "severity": alert.severity,
                "code": alert.code,
                "message": alert.message,
                "status": alert.status,
                "first_seen_at": alert.first_seen_at,
                "last_seen_at": alert.last_seen_at,
                "cleared_at": alert.cleared_at,
                "extra_json": extra_json,
            }
        )
    alerts.sort(key=_alert_sort_value, reverse=True)

    return DiscoveredAssetOut(
        id=asset.id,
        customer_id=asset.customer_id,
        proxy_agent_id=asset.proxy_agent_id,
        asset_class=asset.asset_class,
        source_type=asset.source_type,
        display_name=asset.display_name,
        vendor=asset.vendor,
        model=asset.model,
        serial_number=asset.serial_number,
        firmware_version=asset.firmware_version,
        ip_address=asset.ip_address,
        management_ip=asset.management_ip,
        mac_address=asset.mac_address,
        status=asset.status,
        raw_facts=raw_facts,
        inventory=inventory,
        components=components,
        health=health,
        alerts=alerts,
        first_seen_at=asset.first_seen_at,
        last_seen_at=asset.last_seen_at,
        created_at=asset.created_at,
    )


def _serialize_command(command: ProxyAgentCommand) -> ProxyAgentCommandOut:
    try:
        payload = json.loads(command.payload or "{}")
        if not isinstance(payload, dict):
            payload = {}
    except Exception:
        payload = {}

    return ProxyAgentCommandOut(
        id=command.id,
        proxy_agent_id=command.proxy_agent_id,
        command_type=command.command_type,
        payload=payload,
        status=command.status,
        result=command.result,
        created_at=command.created_at,
        acked_at=command.acked_at,
    )


async def _find_existing_asset(
    customer_id: str,
    asset_class: str,
    serial_number: str,
    management_ip: str,
    ip_address: str,
    mac_address: str,
    db: AsyncSession,
) -> Optional[DiscoveredAsset]:
    normalized_asset_class = asset_class.strip()
    for field, value in (
        ("management_ip", management_ip),
        ("ip_address", ip_address),
        ("mac_address", mac_address),
    ):
        value = value.strip()
        if not value:
            continue
        result = await db.execute(
            select(DiscoveredAsset).where(
                DiscoveredAsset.customer_id == customer_id,
                getattr(DiscoveredAsset, field) == value,
            )
        )
        found = result.scalar_one_or_none()
        if found:
            return found

    if serial_number.strip():
        filters = [
            DiscoveredAsset.customer_id == customer_id,
            DiscoveredAsset.serial_number == serial_number.strip(),
        ]
        if normalized_asset_class:
            filters.append(DiscoveredAsset.asset_class == normalized_asset_class)
        result = await db.execute(
            select(DiscoveredAsset).where(*filters)
        )
        found = result.scalar_one_or_none()
        if found:
            return found

    return None


def _json_dumps(payload: dict[str, object]) -> str:
    return json.dumps(payload or {}, ensure_ascii=False)


async def _persist_asset_details(
    asset: DiscoveredAsset,
    item,
    now: datetime,
    db: AsyncSession,
) -> None:
    if item.inventory:
        result = await db.execute(select(AssetInventory).where(AssetInventory.asset_id == asset.id))
        inventory = result.scalar_one_or_none()
        if not inventory:
            inventory = AssetInventory(asset_id=asset.id)
            db.add(inventory)

        inventory.processor_model = item.inventory.processor_model
        inventory.processor_vendor = item.inventory.processor_vendor
        inventory.processor_count = item.inventory.processor_count
        inventory.physical_cores = item.inventory.physical_cores
        inventory.logical_processors = item.inventory.logical_processors
        inventory.memory_total_gb = item.inventory.memory_total_gb
        inventory.memory_slot_count = item.inventory.memory_slot_count
        inventory.memory_slots_used = item.inventory.memory_slots_used
        inventory.memory_module_count = item.inventory.memory_module_count
        inventory.storage_controller_count = item.inventory.storage_controller_count
        inventory.physical_disk_count = item.inventory.physical_disk_count
        inventory.virtual_disk_count = item.inventory.virtual_disk_count
        inventory.disk_total_gb = item.inventory.disk_total_gb
        inventory.network_interface_count = item.inventory.network_interface_count
        inventory.power_supply_count = item.inventory.power_supply_count
        inventory.raid_summary = item.inventory.raid_summary
        inventory.updated_at = now

    if item.health:
        result = await db.execute(select(AssetHealth).where(AssetHealth.asset_id == asset.id))
        health = result.scalar_one_or_none()
        if not health:
            health = AssetHealth(asset_id=asset.id)
            db.add(health)

        health.overall_status = item.health.overall_status
        health.processor_status = item.health.processor_status
        health.memory_status = item.health.memory_status
        health.storage_status = item.health.storage_status
        health.power_status = item.health.power_status
        health.network_status = item.health.network_status
        health.thermal_status = item.health.thermal_status
        health.power_state = item.health.power_state
        health.alert_count = item.health.alert_count
        health.summary = item.health.summary
        health.updated_at = now

    if item.components:
        await db.execute(delete(AssetComponent).where(AssetComponent.asset_id == asset.id))
        for component in item.components:
            db.add(
                AssetComponent(
                    asset_id=asset.id,
                    component_type=component.component_type,
                    name=component.name,
                    slot=component.slot,
                    model=component.model,
                    manufacturer=component.manufacturer,
                    serial_number=component.serial_number,
                    firmware_version=component.firmware_version,
                    capacity_gb=component.capacity_gb,
                    status=component.status,
                    health=component.health,
                    extra_json=_json_dumps(component.extra_json),
                )
            )

    result = await db.execute(select(AssetAlert).where(AssetAlert.asset_id == asset.id))
    existing_alerts = result.scalars().all()
    existing_by_key = {_alert_identity_from_model(alert): alert for alert in existing_alerts}
    seen_alert_keys: set[str] = set()

    for alert in item.alerts:
        extra_json = alert.extra_json if isinstance(alert.extra_json, dict) else {}
        history_entry = _alert_has_event_history(extra_json)
        key = _alert_identity_from_payload(alert)
        seen_alert_keys.add(key)
        existing = existing_by_key.get(key)
        if existing:
            existing.source = alert.source
            existing.severity = alert.severity
            existing.code = alert.code
            existing.message = alert.message
            existing.status = alert.status
            existing.extra_json = _json_dumps(extra_json)
            existing.first_seen_at = alert.first_seen_at or existing.first_seen_at
            if alert.last_seen_at:
                existing.last_seen_at = alert.last_seen_at
            elif history_entry:
                existing.last_seen_at = existing.last_seen_at or alert.first_seen_at
            else:
                existing.last_seen_at = now
            existing.cleared_at = alert.cleared_at
            continue

        db.add(
            AssetAlert(
                asset_id=asset.id,
                source=alert.source,
                severity=alert.severity,
                code=alert.code,
                message=alert.message,
                status=alert.status,
                first_seen_at=alert.first_seen_at,
                last_seen_at=alert.last_seen_at or (alert.first_seen_at if history_entry else now),
                cleared_at=alert.cleared_at,
                extra_json=_json_dumps(extra_json),
            )
        )

    for existing in existing_alerts:
        key = _alert_identity_from_model(existing)
        if key in seen_alert_keys:
            continue
        extra_json = _load_json_object(existing.extra_json)
        if _alert_has_event_history(extra_json):
            continue
        if existing.status != "cleared":
            existing.status = "cleared"
            existing.cleared_at = now


@router.get("/agents", response_model=list[ProxyAgentOut])
async def list_proxy_agents(customer_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(ProxyAgent).order_by(ProxyAgent.name)
    if customer_id:
        customer = await _resolve_customer(customer_id, db)
        q = q.where(ProxyAgent.customer_id == customer.id)
    result = await db.execute(q)
    return [_serialize_agent(agent) for agent in result.scalars().all()]


@router.post("/agents", response_model=ProxyAgentOut, status_code=201)
async def create_proxy_agent(body: ProxyAgentCreate, db: AsyncSession = Depends(get_db)):
    customer = await _resolve_customer(body.customer_id, db)
    agent = ProxyAgent(
        customer_id=customer.id,
        name=body.name,
        site_name=body.site_name,
        hostname=body.hostname,
        ip_address=body.ip_address,
        mac_address="",
        version=body.version,
        status="not_registered",
        is_registered=False,
        capabilities=", ".join(item.strip() for item in body.capabilities if item.strip()),
        auth_token=(body.auth_token or "").strip() or _new_proxy_token(),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return _serialize_agent(agent)


@router.get("/agents/{agent_id}", response_model=ProxyAgentOut)
async def get_proxy_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProxyAgent).where(ProxyAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Proxy agent not found")
    return _serialize_agent(agent)


@router.post("/agents/{agent_id}/register", response_model=ProxyAgentOut)
async def register_proxy_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProxyAgent).where(ProxyAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Proxy agent not found")

    now = datetime.utcnow()
    agent.is_registered = True
    if not agent.registered_at:
        agent.registered_at = now
    agent.status = "online" if agent.last_checkin else "registered"
    await db.commit()
    await db.refresh(agent)
    return _serialize_agent(agent)


@router.get("/agents/{agent_id}/commands", response_model=list[ProxyAgentCommandOut])
async def list_proxy_agent_commands(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProxyAgentCommand)
        .where(ProxyAgentCommand.proxy_agent_id == agent_id)
        .order_by(ProxyAgentCommand.created_at.desc())
    )
    return [_serialize_command(command) for command in result.scalars().all()]


@router.get("/agents/{agent_id}/commands/{command_id}", response_model=ProxyAgentCommandOut)
async def get_proxy_agent_command(agent_id: str, command_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(ProxyAgentCommand).where(
            ProxyAgentCommand.proxy_agent_id == agent_id,
            ProxyAgentCommand.id == command_id,
        )
    )
    command = result.scalar_one_or_none()
    if not command:
        raise HTTPException(status_code=404, detail="Proxy agent command not found")
    return _serialize_command(command)


@router.post("/agents/{agent_id}/commands", response_model=ProxyAgentCommandOut, status_code=201)
async def create_proxy_agent_command(
    agent_id: str,
    body: ProxyAgentCommandCreate,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(ProxyAgent).where(ProxyAgent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Proxy agent not found")

    command = ProxyAgentCommand(
        proxy_agent_id=agent.id,
        command_type=body.command_type.strip(),
        payload=json.dumps(body.payload or {}, ensure_ascii=False),
    )
    db.add(command)
    await db.commit()
    await db.refresh(command)

    asyncio.create_task(
        _mqtt_publish_proxy(
            agent.id,
            {
                "id": command.id,
                "type": command.command_type,
                "payload": body.payload or {},
            },
        )
    )

    return _serialize_command(command)


@router.get("/assets", response_model=list[DiscoveredAssetOut])
async def list_discovered_assets(
    customer_id: Optional[str] = None,
    proxy_agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
):
    q = (
        select(DiscoveredAsset)
        .options(*_ASSET_QUERY_OPTIONS)
        .order_by(DiscoveredAsset.display_name, DiscoveredAsset.created_at.desc())
    )
    if customer_id:
        customer = await _resolve_customer(customer_id, db)
        q = q.where(DiscoveredAsset.customer_id == customer.id)
    if proxy_agent_id:
        q = q.where(DiscoveredAsset.proxy_agent_id == proxy_agent_id)
    result = await db.execute(q)
    return [_serialize_asset(asset) for asset in result.scalars().all()]


@router.get("/assets/{asset_id}", response_model=DiscoveredAssetOut)
async def get_discovered_asset(asset_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DiscoveredAsset)
        .options(*_ASSET_QUERY_OPTIONS)
        .where(DiscoveredAsset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Discovered asset not found")
    return _serialize_asset(asset)


@router.post("/ingest", response_model=DiscoveryIngestOut)
async def ingest_discovery(body: DiscoveryIngestRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(ProxyAgent).where(ProxyAgent.auth_token == body.agent_token))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=403, detail="Invalid proxy agent token")

    now = datetime.utcnow()
    if body.agent:
        agent.hostname = body.agent.hostname or agent.hostname
        agent.ip_address = body.agent.ip_address or agent.ip_address
        agent.mac_address = body.agent.mac_address or agent.mac_address
        agent.portal_url = body.agent.portal_url or agent.portal_url
        agent.version = body.agent.version or agent.version
        agent.site_name = body.agent.site_name or agent.site_name
        caps = ", ".join(item.strip() for item in body.agent.capabilities if item.strip())
        if caps:
            agent.capabilities = caps
    agent.status = "online" if agent.is_registered else "not_registered"
    agent.last_checkin = now

    created_assets = 0
    updated_assets = 0

    for item in body.assets:
        existing = await _find_existing_asset(
            customer_id=agent.customer_id,
            asset_class=item.asset_class,
            serial_number=item.serial_number,
            management_ip=item.management_ip,
            ip_address=item.ip_address,
            mac_address=item.mac_address,
            db=db,
        )

        raw_facts = json.dumps(item.raw_facts or {}, ensure_ascii=False)

        if existing:
            existing.proxy_agent_id = agent.id
            existing.asset_class = item.asset_class
            existing.source_type = "proxy_agent"
            existing.display_name = item.display_name or existing.display_name
            existing.vendor = item.vendor or existing.vendor
            existing.model = item.model or existing.model
            existing.serial_number = item.serial_number or existing.serial_number
            existing.firmware_version = item.firmware_version or existing.firmware_version
            existing.ip_address = item.ip_address or existing.ip_address
            existing.management_ip = item.management_ip or existing.management_ip
            existing.mac_address = item.mac_address or existing.mac_address
            existing.status = item.status or existing.status
            existing.raw_facts = raw_facts
            existing.last_seen_at = now
            await _persist_asset_details(existing, item, now, db)
            updated_assets += 1
            continue

        asset = DiscoveredAsset(
            customer_id=agent.customer_id,
            proxy_agent_id=agent.id,
            asset_class=item.asset_class,
            source_type="proxy_agent",
            display_name=item.display_name,
            vendor=item.vendor,
            model=item.model,
            serial_number=item.serial_number,
            firmware_version=item.firmware_version,
            ip_address=item.ip_address,
            management_ip=item.management_ip,
            mac_address=item.mac_address,
            status=item.status,
            raw_facts=raw_facts,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(asset)
        await db.flush()
        await _persist_asset_details(asset, item, now, db)
        created_assets += 1

    await db.commit()

    return DiscoveryIngestOut(
        proxy_agent_id=agent.id,
        accepted_assets=len(body.assets),
        created_assets=created_assets,
        updated_assets=updated_assets,
        last_checkin=now,
    )
