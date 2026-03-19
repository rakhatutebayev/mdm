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
import asyncio
from mqtt_publisher import publish_command as _mqtt_publish
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from database import get_db
from models import (
    Customer,
    Device,
    DeviceCommand,
    EnrollmentToken,
    HardwareInventory,
    LogicalDisk,
    MonitorInfo,
    NetworkInfo,
    PhysicalDisk,
    PrinterInfo,
)
from package_builder.release_catalog import find_artifact

router = APIRouter(prefix="/api/v1/mdm/windows", tags=["mdm-agent"])
KNOWN_AGENT_VERSION_FALLBACK = "1.2.0"


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
    manufacturer: str = ""
    model: str = ""
    serial_number: str = ""
    display_size: str = ""
    resolution: str = ""
    refresh_rate: str = ""
    color_depth: str = ""
    connection_type: str = ""
    hdr_support: bool = False
    is_external: bool = True


class HardwareInventoryPayload(BaseModel):
    processor_model: str = ""
    processor_vendor: str = ""
    physical_cores: Optional[int] = None
    logical_processors: Optional[int] = None
    memory_total_gb: Optional[float] = None
    memory_slot_count: Optional[int] = None
    memory_slots_used: Optional[int] = None
    memory_module_count: Optional[int] = None
    machine_class: str = ""
    chassis_type: str = ""
    gpu_model: str = ""
    gpu_manufacturer: str = ""
    gpu_vram_gb: Optional[float] = None
    gpu_driver_version: str = ""


class PhysicalDiskPayload(BaseModel):
    disk_index: Optional[int] = None
    model: str = ""
    serial_number: str = ""
    media_type: str = ""
    interface_type: str = ""
    size_gb: Optional[float] = None


class PrinterPayload(BaseModel):
    name: str = ""
    driver_name: str = ""
    port_name: str = ""
    ip_address: str = ""
    is_default: bool = False
    is_network: bool = False
    is_shared: bool = False
    work_offline: bool = False
    job_count: int = 0
    connection_type: str = ""
    status: str = ""


class LogicalDiskPayload(BaseModel):
    name: str = ""
    volume_name: str = ""
    file_system: str = ""
    drive_type: str = ""
    size_gb: Optional[float] = None
    free_gb: Optional[float] = None
    used_gb: Optional[float] = None


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
    hardware_inventory: Optional[HardwareInventoryPayload] = None
    physical_disks: Optional[list[PhysicalDiskPayload]] = None
    logical_disks: Optional[list[LogicalDiskPayload]] = None
    printers: Optional[list[PrinterPayload]] = None


class CheckinPayload(BaseModel):
    """Periodic heartbeat payload with optional telemetry."""
    model_config = {"coerce_numbers_to_str": False, "extra": "ignore"}

    device_id: str
    agent_version: str = ""
    os_version: str = ""
    ip_address: str = ""
    device_name: str = ""  # sent after rename/reboot so the portal updates immediately
    # Telemetry — all optional, accept float for robustness (PowerShell quirks)
    cpu_pct: Optional[float] = None         # 0–100
    ram_used_gb: Optional[float] = None
    ram_total_gb: Optional[float] = None
    disk_used_gb: Optional[float] = None
    disk_total_gb: Optional[float] = None
    uptime_seconds: Optional[float] = None  # float to accept PS decimal output
    logical_disks: Optional[list[LogicalDiskPayload]] = None
    extra: Optional[dict[str, Any]] = None


class InventoryPayload(BaseModel):
    device_id: str
    device_name: str = ""
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
    enrollment_method: str = "WindowsService"
    agent_version: str = ""
    network: Optional[NetworkPayload] = None
    monitors: Optional[list[MonitorPayload]] = None
    hardware_inventory: Optional[HardwareInventoryPayload] = None
    physical_disks: Optional[list[PhysicalDiskPayload]] = None
    logical_disks: Optional[list[LogicalDiskPayload]] = None
    printers: Optional[list[PrinterPayload]] = None


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


def _version_tuple(value: str) -> tuple[int, ...]:
    parts: list[int] = []
    for chunk in str(value or "").strip().split("."):
        if not chunk.isdigit():
            return ()
        parts.append(int(chunk))
    return tuple(parts)


async def _latest_acked_update_version(device_id: str, db: AsyncSession) -> str:
    result = await db.execute(
        select(DeviceCommand)
        .where(
            DeviceCommand.device_id == device_id,
            DeviceCommand.command_type == "update_agent",
            DeviceCommand.status == "acked",
        )
        .order_by(DeviceCommand.acked_at.desc(), DeviceCommand.created_at.desc())
        .limit(1)
    )
    cmd = result.scalar_one_or_none()
    if not cmd or not cmd.payload:
        return ""
    try:
        payload = _json.loads(cmd.payload)
    except Exception:
        return ""
    return str(payload.get("target_version", "") or "").strip()


async def _effective_agent_version(
    *,
    device_id: str,
    current_version: str,
    reported_version: str,
    db: AsyncSession,
) -> str:
    reported = str(reported_version or "").strip()
    if not reported:
        return ""

    current = str(current_version or "").strip()
    if reported != KNOWN_AGENT_VERSION_FALLBACK:
        return reported

    hinted = await _latest_acked_update_version(device_id, db)
    hinted_tuple = _version_tuple(hinted)
    reported_tuple = _version_tuple(reported)
    current_tuple = _version_tuple(current)

    if hinted_tuple and reported_tuple and hinted_tuple > reported_tuple:
        return hinted
    if current_tuple and reported_tuple and current_tuple > reported_tuple:
        return current
    return reported


async def _apply_inventory(device: Device, body: EnrollPayload | InventoryPayload, db: AsyncSession) -> None:
    device.device_name = body.device_name or device.device_name
    device.platform = body.platform or device.platform
    device.device_type = body.device_type or device.device_type
    device.model = body.model
    device.manufacturer = body.manufacturer
    device.serial_number = body.serial_number
    device.udid = body.udid
    device.os_version = body.os_version
    device.architecture = body.architecture
    device.owner = body.owner
    device.shared_device = body.shared_device
    device.enrollment_method = body.enrollment_method
    if body.agent_version:
        device.agent_version = await _effective_agent_version(
            device_id=device.id,
            current_version=device.agent_version,
            reported_version=body.agent_version,
            db=db,
        )

    if body.network:
        net = body.network
        if device.network:
            device.network.ip_address = net.ip_address
            device.network.mac_address = net.mac_address
            device.network.hostname = net.hostname or net.interface or device.device_name
            device.network.wifi_ssid = net.wifi_ssid
            device.network.connection_type = net.connection_type
            device.network.dns_server = net.dns_server or net.dns_servers
            device.network.default_gateway = net.default_gateway or net.gateway
        else:
            db.add(NetworkInfo(
                device_id=device.id,
                ip_address=net.ip_address,
                mac_address=net.mac_address,
                hostname=net.hostname or net.interface or device.device_name,
                wifi_ssid=net.wifi_ssid,
                connection_type=net.connection_type,
                dns_server=net.dns_server or net.dns_servers,
                default_gateway=net.default_gateway or net.gateway,
            ))

    if body.monitors is not None:
        for existing in list(device.monitors):
            await db.delete(existing)
        for idx, m in enumerate(body.monitors):
            db.add(MonitorInfo(
                device_id=device.id,
                display_index=m.display_index or (idx + 1),
                manufacturer=m.manufacturer,
                model=m.model or m.name or "",
                serial_number=m.serial_number,
                display_size=m.display_size,
                resolution=m.resolution,
                refresh_rate=m.refresh_rate,
                color_depth=m.color_depth,
                connection_type=m.connection_type,
                hdr_support=m.hdr_support,
            ))

    if body.hardware_inventory:
        hw = body.hardware_inventory
        if device.hardware_inventory:
            device.hardware_inventory.processor_model = hw.processor_model
            device.hardware_inventory.processor_vendor = hw.processor_vendor
            device.hardware_inventory.physical_cores = hw.physical_cores
            device.hardware_inventory.logical_processors = hw.logical_processors
            device.hardware_inventory.memory_total_gb = hw.memory_total_gb
            device.hardware_inventory.memory_slot_count = hw.memory_slot_count
            device.hardware_inventory.memory_slots_used = hw.memory_slots_used
            device.hardware_inventory.memory_module_count = hw.memory_module_count
            device.hardware_inventory.machine_class = hw.machine_class
            device.hardware_inventory.chassis_type = hw.chassis_type
            device.hardware_inventory.gpu_model = hw.gpu_model
            device.hardware_inventory.gpu_manufacturer = hw.gpu_manufacturer
            device.hardware_inventory.gpu_vram_gb = hw.gpu_vram_gb
            device.hardware_inventory.gpu_driver_version = hw.gpu_driver_version
        else:
            db.add(HardwareInventory(
                device_id=device.id,
                processor_model=hw.processor_model,
                processor_vendor=hw.processor_vendor,
                physical_cores=hw.physical_cores,
                logical_processors=hw.logical_processors,
                memory_total_gb=hw.memory_total_gb,
                memory_slot_count=hw.memory_slot_count,
                memory_slots_used=hw.memory_slots_used,
                memory_module_count=hw.memory_module_count,
                machine_class=hw.machine_class,
                chassis_type=hw.chassis_type,
                gpu_model=hw.gpu_model,
                gpu_manufacturer=hw.gpu_manufacturer,
                gpu_vram_gb=hw.gpu_vram_gb,
                gpu_driver_version=hw.gpu_driver_version,
            ))

    if body.physical_disks is not None:
        for existing in list(device.physical_disks):
            await db.delete(existing)
        for disk in body.physical_disks:
            db.add(PhysicalDisk(
                device_id=device.id,
                disk_index=disk.disk_index,
                model=disk.model,
                serial_number=disk.serial_number,
                media_type=disk.media_type,
                interface_type=disk.interface_type,
                size_gb=disk.size_gb,
            ))

    if body.logical_disks is not None:
        for existing in list(device.logical_disks):
            await db.delete(existing)
        for disk in body.logical_disks:
            db.add(LogicalDisk(
                device_id=device.id,
                name=disk.name,
                volume_name=disk.volume_name,
                file_system=disk.file_system,
                drive_type=disk.drive_type,
                size_gb=disk.size_gb,
                free_gb=disk.free_gb,
                used_gb=disk.used_gb,
            ))

    if body.printers is not None:
        for existing in list(device.printers):
            await db.delete(existing)
        for p in body.printers:
            db.add(PrinterInfo(
                device_id=device.id,
                name=p.name,
                driver_name=p.driver_name,
                port_name=p.port_name,
                ip_address=p.ip_address,
                is_default=p.is_default,
                is_network=p.is_network,
                is_shared=p.is_shared,
                work_offline=p.work_offline,
                job_count=p.job_count,
                connection_type=p.connection_type,
                status=p.status,
            ))


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
                manufacturer    = m.manufacturer,
                model           = m.model or m.name or "",
                serial_number   = m.serial_number,
                display_size    = m.display_size,
                resolution      = m.resolution,
                refresh_rate    = m.refresh_rate,
                color_depth     = m.color_depth,
                connection_type = m.connection_type,
                hdr_support     = m.hdr_support,
            ))

    if body.hardware_inventory:
        hw = body.hardware_inventory
        db.add(HardwareInventory(
            device_id=device.id,
            processor_model=hw.processor_model,
            processor_vendor=hw.processor_vendor,
            physical_cores=hw.physical_cores,
            logical_processors=hw.logical_processors,
            memory_total_gb=hw.memory_total_gb,
            memory_slot_count=hw.memory_slot_count,
            memory_slots_used=hw.memory_slots_used,
            memory_module_count=hw.memory_module_count,
            machine_class=hw.machine_class,
            chassis_type=hw.chassis_type,
        ))

    if body.physical_disks:
        for disk in body.physical_disks:
            db.add(PhysicalDisk(
                device_id=device.id,
                disk_index=disk.disk_index,
                model=disk.model,
                serial_number=disk.serial_number,
                media_type=disk.media_type,
                interface_type=disk.interface_type,
                size_gb=disk.size_gb,
            ))

    if body.logical_disks:
        for disk in body.logical_disks:
            db.add(LogicalDisk(
                device_id=device.id,
                name=disk.name,
                volume_name=disk.volume_name,
                file_system=disk.file_system,
                drive_type=disk.drive_type,
                size_gb=disk.size_gb,
                free_gb=disk.free_gb,
                used_gb=disk.used_gb,
            ))

    if body.printers:
        for printer in body.printers:
            db.add(PrinterInfo(
                device_id=device.id,
                name=printer.name,
                driver_name=printer.driver_name,
                port_name=printer.port_name,
                ip_address=printer.ip_address,
                is_default=printer.is_default,
                is_network=printer.is_network,
                is_shared=printer.is_shared,
                work_offline=printer.work_offline,
                job_count=printer.job_count,
                connection_type=printer.connection_type,
                status=printer.status,
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
    from models import DeviceMetrics, LogicalDiskMetric

    result = await db.execute(
        select(Device)
        .options(selectinload(Device.network))
        .where(Device.id == body.device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Update device fields
    device.last_checkin = datetime.utcnow()
    if body.agent_version:
        device.agent_version = await _effective_agent_version(
            device_id=device.id,
            current_version=device.agent_version,
            reported_version=body.agent_version,
            db=db,
        )
    if body.os_version:
        device.os_version = body.os_version
    if body.ip_address and device.network:
        device.network.ip_address = body.ip_address
    if body.device_name:
        device.device_name = body.device_name

    # Save metrics snapshot if any telemetry provided
    has_metrics = any([
        body.cpu_pct is not None,
        body.ram_used_gb is not None,
        body.disk_used_gb is not None,
        body.uptime_seconds is not None,
        body.logical_disks,
    ])
    if has_metrics:
        snapshot = DeviceMetrics(
            device_id      = device.id,
            cpu_pct        = body.cpu_pct,
            ram_used_gb    = body.ram_used_gb,
            ram_total_gb   = body.ram_total_gb,
            disk_used_gb   = body.disk_used_gb,
            disk_total_gb  = body.disk_total_gb,
            uptime_seconds = body.uptime_seconds,
            os_version     = body.os_version or device.os_version,
        )
        db.add(snapshot)
        await db.flush()

        for disk in body.logical_disks or []:
            db.add(LogicalDiskMetric(
                metric_id=snapshot.id,
                name=disk.name,
                volume_name=disk.volume_name,
                file_system=disk.file_system,
                drive_type=disk.drive_type,
                size_gb=disk.size_gb,
                free_gb=disk.free_gb,
                used_gb=disk.used_gb,
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


@router.post("/inventory")
async def inventory(body: InventoryPayload, db: AsyncSession = Depends(get_db)):
    """Update full device inventory on a slower cadence than heartbeat."""
    result = await db.execute(
        select(Device)
        .options(
            selectinload(Device.network),
            selectinload(Device.monitors),
            selectinload(Device.hardware_inventory),
            selectinload(Device.physical_disks),
            selectinload(Device.logical_disks),
            selectinload(Device.printers),
        )
        .where(Device.id == body.device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    import logging as _log
    _log.getLogger("mdm.inventory").info(
        "inventory from %s (v%s): monitors=%d hardware=%s",
        body.device_id, body.agent_version,
        len(body.monitors) if body.monitors else 0,
        "yes" if body.hardware_inventory else "no",
    )

    await _apply_inventory(device, body, db)
    device.last_checkin = datetime.utcnow()
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
        .options(selectinload(DeviceMetrics.disk_metrics))
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
            "logical_disks": [
                {
                    "name": disk.name,
                    "volume_name": disk.volume_name,
                    "file_system": disk.file_system,
                    "drive_type": disk.drive_type,
                    "size_gb": disk.size_gb,
                    "free_gb": disk.free_gb,
                    "used_gb": disk.used_gb,
                }
                for disk in m.disk_metrics
            ],
        }

    return {
        "latest":  to_dict(snapshots[0]),
        "history": [to_dict(s) for s in snapshots],
    }


import json as _json

@router.get("/commands")
async def get_commands(device_id: str, db: AsyncSession = Depends(get_db)):
    """Return pending MDM commands for this device and mark them as sent."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Device not found")

    cmds_result = await db.execute(
        select(DeviceCommand)
        .where(DeviceCommand.device_id == device_id, DeviceCommand.status == "pending")
        .order_by(DeviceCommand.created_at)
    )
    cmds = cmds_result.scalars().all()

    out = []
    for cmd in cmds:
        out.append({"id": cmd.id, "type": cmd.command_type, "payload": _json.loads(cmd.payload)})
        cmd.status = "sent"
    await db.commit()
    return {"device_id": device_id, "commands": out}


class CommandAckPayload(BaseModel):
    command_id: str
    status: str = "acked"   # "acked" | "failed"
    result: Optional[str] = None


@router.post("/commands/ack")
async def ack_command(body: CommandAckPayload, db: AsyncSession = Depends(get_db)):
    """Agent acknowledges a command result."""
    result = await db.execute(select(DeviceCommand).where(DeviceCommand.id == body.command_id))
    cmd = result.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    cmd.status = body.status
    cmd.result = body.result
    cmd.acked_at = datetime.utcnow()
    if body.status == "acked" and cmd.command_type == "update_agent":
        target_version = ""
        try:
            payload = _json.loads(cmd.payload or "{}")
            target_version = str(payload.get("target_version", "") or "").strip()
        except Exception:
            target_version = ""
        if target_version:
            device_result = await db.execute(select(Device).where(Device.id == cmd.device_id))
            device = device_result.scalar_one_or_none()
            if device:
                device.agent_version = target_version
    await db.commit()
    return {"status": "ok", "command_id": body.command_id}


# ── Portal: issue commands ─────────────────────────────────────────────────────

class RenameCommandPayload(BaseModel):
    device_id: str
    new_name: str
    restart_after: bool = True


@router.post("/portal/commands/rename")
async def portal_rename_computer(body: RenameCommandPayload, db: AsyncSession = Depends(get_db)):
    """Portal: queue a rename_computer command for a device."""
    result = await db.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    new_name = body.new_name.strip()
    if not new_name or len(new_name) > 15 or not all(c.isalnum() or c == '-' for c in new_name):
        raise HTTPException(status_code=422, detail="Invalid computer name (max 15 chars, letters/digits/hyphens only)")

    cmd = DeviceCommand(
        device_id=body.device_id,
        command_type="rename_computer",
        payload=_json.dumps({"new_name": new_name, "restart_after": body.restart_after}),
    )
    db.add(cmd)
    await db.commit()
    # Publish via MQTT for instant delivery (fallback: agent HTTP poll)
    asyncio.create_task(_mqtt_publish(
        body.device_id,
        {"id": cmd.id, "type": "rename_computer", "payload": {"new_name": new_name, "restart_after": body.restart_after}},
    ))
    return {"status": "queued", "command_id": cmd.id, "new_name": new_name}


@router.get("/portal/commands/{command_id}")
async def portal_get_command_status(command_id: str, db: AsyncSession = Depends(get_db)):
    """Portal: check current status of a queued command."""
    result = await db.execute(select(DeviceCommand).where(DeviceCommand.id == command_id))
    cmd = result.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")
    return {
        "command_id": cmd.id,
        "command_type": cmd.command_type,
        "status": cmd.status,          # pending | sent | acked | failed
        "result": cmd.result,
        "payload": _json.loads(cmd.payload),
        "created_at": cmd.created_at.isoformat() if cmd.created_at else None,
        "acked_at": cmd.acked_at.isoformat() if cmd.acked_at else None,
    }


class UpdateAgentPayload(BaseModel):
    device_id: str


@router.post("/portal/commands/update-agent")
async def portal_update_agent(body: UpdateAgentPayload, db: AsyncSession = Depends(get_db)):
    """Portal: queue an update_agent command — agent will download and reinstall itself."""
    result = await db.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Resolve the latest EXE artifact URL from the catalog
    release, artifact = find_artifact("exe", "x64")
    if not release or not artifact:
        raise HTTPException(status_code=404, detail="No EXE artifact found in release catalog")

    target_version = str(release.get("version", ""))
    download_url   = str(artifact.get("url", ""))
    sha256         = str(artifact.get("sha256", "") or "")
    if not sha256:
        raise HTTPException(status_code=500, detail="Release artifact is missing sha256")

    cmd = DeviceCommand(
        device_id=body.device_id,
        command_type="update_agent",
        payload=_json.dumps({
            "download_url": download_url,
            "target_version": target_version,
            "sha256": sha256,
        }),
    )
    db.add(cmd)
    await db.commit()
    asyncio.create_task(_mqtt_publish(
        body.device_id,
        {"id": cmd.id, "type": "update_agent", "payload": {
            "download_url": download_url,
            "target_version": target_version,
            "sha256": sha256,
        }},
    ))
    return {"status": "queued", "command_id": cmd.id, "target_version": target_version}


class RestartAgentPayload(BaseModel):
    device_id: str


@router.post("/portal/commands/restart-agent")
async def portal_restart_agent(body: RestartAgentPayload, db: AsyncSession = Depends(get_db)):
    """Portal: queue a restart_agent command — agent restarts and immediately sends full inventory."""
    result = await db.execute(select(Device).where(Device.id == body.device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    cmd = DeviceCommand(
        device_id=body.device_id,
        command_type="restart_agent",
        payload=_json.dumps({}),
    )
    db.add(cmd)
    await db.commit()
    asyncio.create_task(_mqtt_publish(
        body.device_id,
        {"id": cmd.id, "type": "restart_agent", "payload": {}},
    ))
    return {"status": "queued", "command_id": cmd.id}


@router.get("/portal/latest-version")
async def portal_latest_version():
    """Return the latest agent version from the release catalog (for UI display)."""
    from package_builder.release_catalog import find_artifact
    release, _ = find_artifact("exe", "x64")
    return {"version": str(release.get("version", "")) if release else None}


# ── Decommission ──────────────────────────────────────────────────────────────

class DecommissionPayload(BaseModel):
    device_id: str
    reason: str = "Agent uninstalled"


@router.post("/decommission")
async def decommission(body: DecommissionPayload, db: AsyncSession = Depends(get_db)):
    """Called when the Windows agent is removed from the device."""
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
