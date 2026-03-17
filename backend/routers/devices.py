"""Devices router."""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from database import get_db
from models import Device, Customer
from schemas import DeviceCreate, DeviceListOut, DeviceDetailOut, DeviceStatusUpdate

router = APIRouter(prefix="/api/v1/devices", tags=["devices"])


@router.get("", response_model=list[DeviceListOut])
async def list_devices(customer_id: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    q = select(Device).order_by(Device.device_name)
    if customer_id:
        # Accept both UUID and slug
        cust = await db.execute(
            select(Customer).where(
                (Customer.id == customer_id) | (Customer.slug == customer_id)
            )
        )
        customer = cust.scalar_one_or_none()
        if customer:
            q = q.where(Device.customer_id == customer.id)
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/{device_id}", response_model=DeviceDetailOut)
async def get_device(device_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Device)
        .options(
            selectinload(Device.network),
            selectinload(Device.monitors),
            selectinload(Device.hardware_inventory),
            selectinload(Device.physical_disks),
            selectinload(Device.logical_disks),
            selectinload(Device.printers),
            selectinload(Device.customer),
        )
        .where(Device.id == device_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    # Build the response dict manually to inject customer_name
    d = device
    return DeviceDetailOut(
        id=d.id,
        customer_id=d.customer_id,
        device_name=d.device_name,
        platform=d.platform,
        device_type=d.device_type,
        model=d.model,
        manufacturer=d.manufacturer,
        serial_number=d.serial_number,
        udid=d.udid,
        os_version=d.os_version,
        architecture=d.architecture,
        shared_device=d.shared_device,
        owner=d.owner,
        enrollment_method=d.enrollment_method,
        status=d.status,
        enrolled_at=d.enrolled_at,
        last_checkin=d.last_checkin,
        agent_version=d.agent_version,
        network=d.network,
        monitors=d.monitors,
        hardware_inventory=d.hardware_inventory,
        physical_disks=d.physical_disks,
        logical_disks=d.logical_disks,
        printers=d.printers,
        customer_name=d.customer.name if d.customer else "",
    )


@router.post("", response_model=DeviceDetailOut, status_code=201)
async def create_device(body: DeviceCreate, db: AsyncSession = Depends(get_db)):
    from models import HardwareInventory, LogicalDisk, MonitorInfo, NetworkInfo, PhysicalDisk, EnrollmentToken, PrinterInfo

    # ── Validate enrollment token ─────────────────────────────────────────────
    if body.enrollment_token:
        tok_result = await db.execute(
            select(EnrollmentToken).where(
                EnrollmentToken.token == body.enrollment_token,
                EnrollmentToken.revoked == False,  # noqa
            )
        )
        if not tok_result.scalar_one_or_none():
            raise HTTPException(status_code=403, detail="Invalid or revoked enrollment token")

    # ── Create Device row ─────────────────────────────────────────────────────
    device_fields = {
        k: v for k, v in body.model_dump().items()
        if k not in (
            "network",
            "monitors",
            "hardware_inventory",
            "physical_disks",
            "logical_disks",
            "printers",
            "enrollment_token",
        )
    }
    device_fields["status"] = "Pending"
    device_fields["enrolled_at"] = datetime.utcnow()
    device = Device(**device_fields)
    db.add(device)
    await db.flush()  # get device.id before adding relations

    # ── Persist NetworkInfo ───────────────────────────────────────────────────
    if body.network:
        net = body.network
        # normalise PS1 alias fields
        dns  = net.dns_server or net.dns_servers
        gw   = net.default_gateway or net.gateway
        host = net.hostname or net.interface or ""
        db.add(NetworkInfo(
            device_id      = device.id,
            ip_address     = net.ip_address,
            mac_address    = net.mac_address,
            hostname       = host,
            wifi_ssid      = net.wifi_ssid,
            connection_type= net.connection_type,
            dns_server     = dns,
            default_gateway= gw,
        ))

    # ── Persist MonitorInfo ───────────────────────────────────────────────────
    if body.monitors:
        for idx, m in enumerate(body.monitors):
            db.add(MonitorInfo(
                device_id      = device.id,
                display_index  = m.display_index or (idx + 1),
                model          = m.model or m.name or "",
                serial_number  = m.serial_number,
                display_size   = m.display_size,
                resolution     = m.resolution,
                refresh_rate   = m.refresh_rate,
                color_depth    = m.color_depth,
                connection_type= m.connection_type,
                hdr_support    = m.hdr_support,
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
    return await get_device(device.id, db)


@router.patch("/{device_id}/status", response_model=DeviceListOut)
async def update_device_status(
    device_id: str,
    body: DeviceStatusUpdate,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")

    allowed = {"Enrolled", "Deprovisioned", "Failed", "Pending"}
    if body.status not in allowed:
        raise HTTPException(status_code=400, detail=f"Status must be one of {allowed}")

    device.status = body.status
    if body.status == "Enrolled" and not device.enrolled_at:
        device.enrolled_at = datetime.utcnow()
    await db.commit()
    await db.refresh(device)
    return device


@router.delete("/{device_id}", status_code=204)
async def delete_device(device_id: str, db: AsyncSession = Depends(get_db)):
    """Permanently delete a device and all its related records."""
    result = await db.execute(select(Device).where(Device.id == device_id))
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    await db.delete(device)
    await db.commit()

