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
        customer_name=d.customer.name if d.customer else "",
    )


@router.post("", response_model=DeviceDetailOut, status_code=201)
async def create_device(body: DeviceCreate, db: AsyncSession = Depends(get_db)):
    device = Device(**body.model_dump())
    db.add(device)
    await db.commit()
    await db.refresh(device)
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
