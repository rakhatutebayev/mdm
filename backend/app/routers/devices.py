from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel

from app.db import get_db
from app.models.device import Device, DevicePlatform, DeviceStatus, EnrollmentType
from app.models.command import MDMCommand, CommandType, CommandStatus
from app.models.user import User, UserRole
from app.routers.auth import get_current_user, require_role
from app.services.apple_mdm import send_apple_push
from app.services.android_emm import send_android_command

router = APIRouter(prefix="/devices", tags=["devices"])


class DeviceOut(BaseModel):
    id: str
    name: Optional[str]
    model: Optional[str]
    serial_number: Optional[str]
    platform: DevicePlatform
    status: DeviceStatus
    enrollment_type: EnrollmentType
    os_version: Optional[str]
    is_byod: bool
    last_seen: Optional[datetime]
    enrolled_at: Optional[datetime]
    owner_id: Optional[str]
    device_info: Optional[dict] = None

    class Config:
        from_attributes = True


class DeviceListResponse(BaseModel):
    total: int
    devices: List[DeviceOut]


class SendCommandRequest(BaseModel):
    command: CommandType
    payload: Optional[dict] = {}


class CommandOut(BaseModel):
    id: str
    command_type: CommandType
    status: CommandStatus
    created_at: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=DeviceListResponse)
async def list_devices(
    platform: Optional[DevicePlatform] = None,
    status: Optional[DeviceStatus] = None,
    is_byod: Optional[bool] = None,
    search: Optional[str] = None,
    offset: int = 0,
    limit: int = Query(50, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Device).where(Device.org_id == current_user.org_id)
    if platform:
        query = query.where(Device.platform == platform)
    if status:
        query = query.where(Device.status == status)
    if is_byod is not None:
        query = query.where(Device.is_byod == is_byod)
    if search:
        query = query.where(
            Device.name.ilike(f"%{search}%") |
            Device.serial_number.ilike(f"%{search}%") |
            Device.model.ilike(f"%{search}%")
        )

    total_result = await db.execute(select(func.count()).select_from(query.subquery()))
    total = total_result.scalar()

    query = query.offset(offset).limit(limit).order_by(Device.enrolled_at.desc())
    result = await db.execute(query)
    devices = result.scalars().all()

    return DeviceListResponse(total=total, devices=devices)


@router.get("/{device_id}", response_model=DeviceOut)
async def get_device(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.org_id == current_user.org_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    return device


@router.post("/{device_id}/command", response_model=CommandOut)
async def send_command(
    device_id: str,
    body: SendCommandRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.org_id == current_user.org_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")
    if device.status not in [DeviceStatus.ENROLLED, DeviceStatus.SUPERVISED]:
        raise HTTPException(400, f"Device is not enrolled (status: {device.status})")

    cmd = MDMCommand(
        device_id=device.id,
        issued_by=current_user.id,
        command_type=body.command,
        payload=body.payload or {},
    )
    db.add(cmd)
    await db.flush()

    # Send push notification to device
    try:
        if device.platform in [DevicePlatform.IOS, DevicePlatform.IPADOS, DevicePlatform.MACOS]:
            await send_apple_push(device.push_token)
            cmd.status = CommandStatus.SENT
            cmd.sent_at = datetime.utcnow()
        elif device.platform == DevicePlatform.ANDROID:
            await send_android_command(device, body.command, body.payload or {})
            cmd.status = CommandStatus.SENT
            cmd.sent_at = datetime.utcnow()
    except Exception as e:
        cmd.status = CommandStatus.ERROR
        cmd.error_message = str(e)

    await db.commit()
    await db.refresh(cmd)
    return cmd


@router.get("/{device_id}/commands", response_model=List[CommandOut])
async def list_commands(
    device_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Verify device belongs to org
    dev_result = await db.execute(
        select(Device).where(Device.id == device_id, Device.org_id == current_user.org_id)
    )
    if not dev_result.scalar_one_or_none():
        raise HTTPException(404, "Device not found")

    result = await db.execute(
        select(MDMCommand)
        .where(MDMCommand.device_id == device_id)
        .order_by(MDMCommand.created_at.desc())
        .limit(50)
    )
    return result.scalars().all()


@router.delete("/{device_id}")
async def unenroll_device(
    device_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Device).where(Device.id == device_id, Device.org_id == current_user.org_id)
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(404, "Device not found")

    device.status = DeviceStatus.UNENROLLED
    await db.commit()
    return {"message": "Device unenrolled"}
