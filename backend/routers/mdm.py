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
    """Periodic heartbeat payload."""
    device_id: str
    agent_version: str = ""
    os_version: str = ""
    ip_address: str = ""
    # Additional fields (future)
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
        status          = "Enrolled",
        enrolled_at     = datetime.utcnow(),
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
    """Heartbeat from the Windows agent. Updates last_checkin timestamp."""

    result = await db.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    device.last_checkin = datetime.utcnow()
    if body.agent_version:
        device.agent_version = body.agent_version
    if body.os_version:
        device.os_version = body.os_version

    # Update IP if changed
    if body.ip_address and device.network:
        device.network.ip_address = body.ip_address

    await db.commit()
    return {"status": "ok", "device_id": device.id}


# ── Commands ──────────────────────────────────────────────────────────────────

@router.get("/commands")
async def get_commands(device_id: str, db: AsyncSession = Depends(get_db)):
    """Return pending MDM commands for this device (reserved for future use)."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Device not found")
    # No commands implemented yet
    return {"device_id": device_id, "commands": []}
