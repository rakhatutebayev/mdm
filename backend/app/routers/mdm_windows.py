"""
Windows MDM Router (Agent-Based)

Windows devices run a PowerShell agent that:
1. Checks in every 15 minutes with hardware inventory
2. Fetches pending commands from this endpoint
3. Reports command execution results

No OMA-DM required — works on Windows 10 and 11 out of the box.
"""
import uuid
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db
from app.models.device import Device, DevicePlatform, DeviceStatus, EnrollmentType
from app.models.command import MDMCommand, CommandStatus
from app.models.enrollment import EnrollmentToken
from app.models.user import User, UserRole
from app.routers.auth import get_current_user, require_role

router = APIRouter(prefix="/mdm/windows", tags=["windows-mdm"])


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class MonitorInfo(BaseModel):
    model: str = ""
    serial: str = ""
    manufacturer: str = ""


class WindowsCheckinPayload(BaseModel):
    """Payload that the PowerShell agent sends on every check-in."""
    device_token: str                          # enrollment token used to register
    hostname: str
    serial_number: str = ""
    os_version: str = ""
    model: str = ""
    manufacturer: str = ""
    ram_gb: float = 0
    disk_gb: float = 0
    current_user: str = ""
    monitors: List[MonitorInfo] = []
    ip_address: str = ""
    mac_address: str = ""
    bios_version: str = ""
    cpu_model: str = ""
    domain_joined: bool = False
    entra_joined: bool = False          # true if joined to Microsoft Entra


class WindowsCommandAck(BaseModel):
    status: str        # "success" | "failed"
    output: str = ""


class WindowsDeviceResponse(BaseModel):
    device_id: str
    commands: List[dict] = []
    check_in_interval_minutes: int = 15


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/checkin", response_model=WindowsDeviceResponse)
async def windows_checkin(
    payload: WindowsCheckinPayload,
    db: AsyncSession = Depends(get_db),
):
    """
    Called by the Windows agent every N minutes.
    Creates the device record on first check-in, updates it on subsequent calls.
    Returns pending commands for the agent to execute.
    """
    # Validate enrollment token
    result = await db.execute(
        select(EnrollmentToken).where(EnrollmentToken.token == payload.device_token)
    )
    token = result.scalar_one_or_none()

    if not token:
        raise HTTPException(status_code=401, detail="Invalid enrollment token")

    if token.expires_at and token.expires_at < datetime.utcnow():
        raise HTTPException(status_code=401, detail="Enrollment token expired")

    if token.max_uses and token.use_count >= token.max_uses:
        raise HTTPException(status_code=401, detail="Enrollment token usage limit reached")

    # Build hardware info dict
    hardware_info = {
        "serial_number": payload.serial_number,
        "model": payload.model,
        "manufacturer": payload.manufacturer,
        "ram_gb": payload.ram_gb,
        "disk_gb": payload.disk_gb,
        "bios_version": payload.bios_version,
        "cpu_model": payload.cpu_model,
        "ip_address": payload.ip_address,
        "mac_address": payload.mac_address,
        "current_user": payload.current_user,
        "domain_joined": payload.domain_joined,
        "entra_joined": payload.entra_joined,
        "monitors": [m.dict() for m in payload.monitors],
    }

    # Find existing device by serial number or hostname
    device = None
    if payload.serial_number:
        result = await db.execute(
            select(Device).where(
                Device.org_id == str(token.org_id),
                Device.device_info["serial_number"].as_string() == payload.serial_number,
            )
        )
        device = result.scalar_one_or_none()

    if not device:
        # First check-in — create device
        device = Device(
            id=uuid.uuid4(),
            name=payload.hostname,
            platform=DevicePlatform.WINDOWS,
            enrollment_type=EnrollmentType.AGENT,
            status=DeviceStatus.ENROLLED,
            org_id=token.org_id,
            enrolled_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
            os_version=payload.os_version,
            device_info=hardware_info,
        )
        db.add(device)
        # Increment token usage
        token.use_count = (token.use_count or 0) + 1
        await db.commit()
        await db.refresh(device)
    else:
        # Subsequent check-ins — update
        device.last_seen = datetime.utcnow()
        device.os_version = payload.os_version
        device.device_info = hardware_info
        device.name = payload.hostname
        if device.status == DeviceStatus.UNENROLLED:
            device.status = DeviceStatus.ENROLLED
        await db.commit()

    # Fetch pending commands for this device
    result = await db.execute(
        select(MDMCommand).where(
            MDMCommand.device_id == device.id,
            MDMCommand.status == CommandStatus.PENDING,
        )
    )
    pending_commands = result.scalars().all()

    commands_out = [
        {
            "id": str(cmd.id),
            "command_type": cmd.command_type,
            "payload": cmd.payload or {},
        }
        for cmd in pending_commands
    ]

    return WindowsDeviceResponse(
        device_id=str(device.id),
        commands=commands_out,
        check_in_interval_minutes=15,
    )


@router.post("/commands/{command_id}/ack")
async def ack_command(
    command_id: str,
    ack: WindowsCommandAck,
    db: AsyncSession = Depends(get_db),
):
    """Agent calls this after executing a command to report the result."""
    result = await db.execute(
        select(MDMCommand).where(MDMCommand.id == uuid.UUID(command_id))
    )
    cmd = result.scalar_one_or_none()
    if not cmd:
        raise HTTPException(status_code=404, detail="Command not found")

    cmd.status = CommandStatus.ACKNOWLEDGED if ack.status == "success" else CommandStatus.FAILED
    cmd.response = {"output": ack.output, "reported_at": datetime.utcnow().isoformat()}
    await db.commit()

    return {"status": "ok"}


@router.get("/commands/{device_id}")
async def get_pending_commands(
    device_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Admin: view pending commands for a Windows device."""
    result = await db.execute(
        select(MDMCommand).where(
            MDMCommand.device_id == uuid.UUID(device_id),
        )
    )
    cmds = result.scalars().all()
    return [
        {
            "id": str(c.id),
            "command_type": c.command_type,
            "status": c.status,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c in cmds
    ]
