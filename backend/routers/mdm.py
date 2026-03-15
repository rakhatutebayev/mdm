"""MDM Windows agent compat router.

Handles endpoints called by the Windows MDM agent:
  POST /api/v1/mdm/windows/enroll   — initial enrollment
  POST /api/v1/mdm/windows/checkin  — periodic check-in / heartbeat
  GET  /api/v1/mdm/windows/commands — pending commands for the device
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Device, NetworkInfo, MonitorInfo, EnrollmentToken, Customer

router = APIRouter(prefix="/api/v1/mdm/windows", tags=["mdm-agent"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class NetworkPayload(BaseModel):
    ip_address: str = ""
    mac_address: str = ""
    hostname: str = ""
    wifi_ssid: str = ""
    connection_type: str = ""
    dns_server: str = ""
    dns_servers: str = ""   # alias
    default_gateway: str = ""
    gateway: str = ""       # alias
    interface: str = ""     # alias


class MonitorPayload(BaseModel):
    display_index: int = 1
    name: str = ""
    model: str = ""
    serial_number: str = ""
    resolution: str = ""
    refresh_rate: str = ""
    color_depth: str = ""
    connection_type: str = ""
    hdr_support: bool = False
    is_external: bool = True


class EnrollPayload(BaseModel):
    """Payload the Windows PS1 agent sends on first run."""
    customer_id: str
    enrollment_token: str
    device_name: str
    platform: str = "Windows"
    device_type: str = "Desktop"
    model: str = ""
    manufacturer: str = ""
    serial_number: str = ""
    udid: str = ""
    os_version: str = ""
    architecture: str = ""
    owner: str = ""
    shared_device: bool = False
    enrollment_method: str = "Agent"
    agent_version: str = ""
    network: Optional[NetworkPayload] = None
    monitors: Optional[list[MonitorPayload]] = None


class CheckinPayload(BaseModel):
    """Periodic heartbeat payload with optional telemetry."""
    model_config = {"coerce_numbers_to_str": False, "extra": "ignore"}

    device_id: str
    agent_version: str = ""
    os_version: str = ""
    ip_address: str = ""
    # Telemetry — all optional, accept float for robustness (PowerShell quirks)
    cpu_pct: Optional[float] = None         # 0–100
    ram_used_gb: Optional[float] = None
    ram_total_gb: Optional[float] = None
    disk_used_gb: Optional[float] = None
    disk_total_gb: Optional[float] = None
    uptime_seconds: Optional[float] = None  # float to accept PS decimal output
    extra: Optional[dict[str, Any]] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _resolve_customer(customer_id: str, db: AsyncSession) -> Customer:
    result = await db.execute(
        select(Customer).where(
            (Customer.id == customer_id) | (Customer.slug == customer_id)
        )
    )
    customer = result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail=f"Customer not found: {customer_id}")
    return customer


# ── Enroll ────────────────────────────────────────────────────────────────────

@router.post("/enroll", status_code=201)
async def enroll_device(body: EnrollPayload, db: AsyncSession = Depends(get_db)):
    """Register a new Windows device. Called by the PS1 install script."""

    customer = await _resolve_customer(body.customer_id, db)

    # Validate enrollment token
    tok = await db.execute(
        select(EnrollmentToken).where(
            EnrollmentToken.token == body.enrollment_token,
            EnrollmentToken.revoked == False,  # noqa
        )
    )
    if not tok.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Invalid or revoked enrollment token")

    # Check if device already enrolled (by UDID or serial number)
    if body.udid:
        existing = await db.execute(select(Device).where(Device.udid == body.udid))
        if dev := existing.scalar_one_or_none():
            # Update last_checkin and return existing
            dev.last_checkin = datetime.utcnow()
            await db.commit()
            return {"device_id": dev.id, "status": dev.status, "message": "Device already enrolled"}

    device = Device(
        customer_id     = customer.id,
        device_name     = body.device_name,
        platform        = body.platform,
        device_type     = body.device_type,
        model           = body.model,
        manufacturer    = body.manufacturer,
        serial_number   = body.serial_number,
        udid            = body.udid,
        os_version      = body.os_version,
        architecture    = body.architecture,
        owner           = body.owner,
        shared_device   = body.shared_device,
        enrollment_method = body.enrollment_method,
        agent_version   = body.agent_version,
        status          = "Pending",
        enrolled_at     = None,
        last_checkin    = datetime.utcnow(),
    )
    db.add(device)
    await db.flush()

    if body.network:
        net = body.network
        db.add(NetworkInfo(
            device_id       = device.id,
            ip_address      = net.ip_address,
            mac_address     = net.mac_address,
            hostname        = net.hostname or net.interface or body.device_name,
            wifi_ssid       = net.wifi_ssid,
            connection_type = net.connection_type,
            dns_server      = net.dns_server or net.dns_servers,
            default_gateway = net.default_gateway or net.gateway,
        ))

    if body.monitors:
        for idx, m in enumerate(body.monitors):
            db.add(MonitorInfo(
                device_id       = device.id,
                display_index   = m.display_index or (idx + 1),
                model           = m.model or m.name or "",
                serial_number   = m.serial_number,
                resolution      = m.resolution,
                refresh_rate    = m.refresh_rate,
                color_depth     = m.color_depth,
                connection_type = m.connection_type,
                hdr_support     = m.hdr_support,
            ))

    await db.commit()
    return {
        "device_id": device.id,
        "status": "Enrolled",
        "message": f"Device '{body.device_name}' enrolled successfully",
    }


# ── Check-in ──────────────────────────────────────────────────────────────────

@router.post("/checkin")
async def checkin(body: CheckinPayload, db: AsyncSession = Depends(get_db)):
    """Heartbeat from the Windows agent. Updates last_checkin and saves metrics."""
    from models import DeviceMetrics

    result = await db.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Update device fields
    device.last_checkin = datetime.utcnow()
    if body.agent_version:
        device.agent_version = body.agent_version
    if body.os_version:
        device.os_version = body.os_version
    if body.ip_address and device.network:
        device.network.ip_address = body.ip_address

    # Save metrics snapshot if any telemetry provided
    has_metrics = any([
        body.cpu_pct is not None,
        body.ram_used_gb is not None,
        body.disk_used_gb is not None,
        body.uptime_seconds is not None,
    ])
    if has_metrics:
        db.add(DeviceMetrics(
            device_id      = device.id,
            cpu_pct        = body.cpu_pct,
            ram_used_gb    = body.ram_used_gb,
            ram_total_gb   = body.ram_total_gb,
            disk_used_gb   = body.disk_used_gb,
            disk_total_gb  = body.disk_total_gb,
            uptime_seconds = body.uptime_seconds,
            os_version     = body.os_version or device.os_version,
        ))
        # Prune old snapshots — keep last 48 (2 days @ 15min interval)
        old = await db.execute(
            select(DeviceMetrics)
            .where(DeviceMetrics.device_id == device.id)
            .order_by(DeviceMetrics.recorded_at.desc())
            .offset(48)
        )
        for row in old.scalars().all():
            await db.delete(row)

    await db.commit()
    return {"status": "ok", "device_id": device.id}


# ── Metrics history ───────────────────────────────────────────────────────────

@router.get("/metrics")
async def get_metrics(device_id: str, db: AsyncSession = Depends(get_db)):
    """Return latest metrics snapshot + 24h history for charts."""
    from models import DeviceMetrics

    result = await db.execute(select(Device).where(Device.id == device_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Device not found")

    rows = await db.execute(
        select(DeviceMetrics)
        .where(DeviceMetrics.device_id == device_id)
        .order_by(DeviceMetrics.recorded_at.desc())
        .limit(96)
    )
    snapshots = rows.scalars().all()

    if not snapshots:
        return {"latest": None, "history": []}

    def to_dict(m: DeviceMetrics):
        return {
            "recorded_at":   m.recorded_at.isoformat(),
            "cpu_pct":       m.cpu_pct,
            "ram_used_gb":   m.ram_used_gb,
            "ram_total_gb":  m.ram_total_gb,
            "disk_used_gb":  m.disk_used_gb,
            "disk_total_gb": m.disk_total_gb,
            "uptime_seconds": m.uptime_seconds,
        }

    return {
        "latest":  to_dict(snapshots[0]),
        "history": [to_dict(s) for s in snapshots],
    }


# ── Commands ──────────────────────────────────────────────────────────────────

@router.get("/commands")
async def get_commands(device_id: str, db: AsyncSession = Depends(get_db)):
    """Return pending MDM commands for this device (reserved for future use)."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Device not found")
    # No commands implemented yet
    return {"device_id": device_id, "commands": []}


# ── Decommission ──────────────────────────────────────────────────────────────

class DecommissionPayload(BaseModel):
    device_id: str
    reason: str = "Agent uninstalled"


@router.post("/decommission")
async def decommission(body: DecommissionPayload, db: AsyncSession = Depends(get_db)):
    """Called by uninstall.ps1 when the MSI agent is removed from the device."""
    result = await db.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if not device:
        # Don't error — device might have been deleted from MDM already
        return {"status": "ok", "message": "Device not found, nothing to decommission"}

    device.status = "Deprovisioned"
    device.last_checkin = datetime.utcnow()
    await db.commit()

    return {
        "status": "ok",
        "device_id": body.device_id,
        "message": f"Device decommissioned: {body.reason}",
    }
