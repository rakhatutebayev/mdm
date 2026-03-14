"""
Apple MDM Protocol Endpoints

Apple MDM check-in and command fetching endpoints.
These must be served over HTTPS with a valid SSL certificate!

References:
- https://developer.apple.com/documentation/devicemanagement
- https://developer.apple.com/documentation/devicemanagement/implementing_device_management
"""
import uuid
import plistlib
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db import get_db
from app.models.device import Device, DevicePlatform, DeviceStatus, EnrollmentType
from app.models.command import MDMCommand, CommandStatus
from app.config import get_settings

router = APIRouter(prefix="/mdm/apple", tags=["apple-mdm"])
settings = get_settings()


@router.get("/enroll/{token}")
async def apple_enrollment_profile(token: str, db: AsyncSession = Depends(get_db)):
    """
    Returns a signed .mobileconfig MDM enrollment profile.
    In production: sign with APNs push certificate.
    """
    from app.models.enrollment import EnrollmentToken
    result = await db.execute(select(EnrollmentToken).where(EnrollmentToken.token == token))
    enrollment = result.scalar_one_or_none()

    if not enrollment or not enrollment.is_valid:
        raise HTTPException(404, "Invalid or expired enrollment token")

    # Build the MDM payload (unsigned for now — must be signed in production)
    payload_uuid = str(uuid.uuid4()).upper()
    profile = {
        "PayloadType": "Configuration",
        "PayloadVersion": 1,
        "PayloadDisplayName": "NOCKO MDM",
        "PayloadDescription": "Enrolls device into NOCKO MDM",
        "PayloadIdentifier": f"com.nocko.mdm.{payload_uuid}",
        "PayloadUUID": payload_uuid,
        "PayloadContent": [
            {
                "PayloadType": "com.apple.mdm",
                "PayloadVersion": 1,
                "PayloadIdentifier": f"com.nocko.mdm.config.{payload_uuid}",
                "PayloadUUID": str(uuid.uuid4()).upper(),
                "PayloadDisplayName": "MDM",
                "ServerURL": f"{settings.MDM_SERVER_URL}/api/v1/mdm/apple/checkin",
                "CheckInURL": f"{settings.MDM_SERVER_URL}/api/v1/mdm/apple/checkin",
                "Topic": settings.APPLE_MDM_TOPIC or "com.apple.mgmt.External.placeholder",
                "IdentityCertificateUUID": str(uuid.uuid4()).upper(),
                "AccessRights": 8191,
                "CheckOutWhenRemoved": True,
                "SignMessage": False,
            }
        ],
    }

    enrollment.use_count += 1
    if enrollment.use_count >= enrollment.max_uses:
        enrollment.is_used = True
    await db.commit()

    plist_data = plistlib.dumps(profile)
    return Response(
        content=plist_data,
        media_type="application/x-apple-aspen-config",
        headers={"Content-Disposition": "attachment; filename=nocko-mdm.mobileconfig"},
    )


@router.put("/checkin")
@router.post("/checkin")
async def apple_checkin(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Apple MDM Check-In endpoint.
    Handles: Authenticate, TokenUpdate, CheckOut messages.
    """
    body = await request.body()
    try:
        plist_data = plistlib.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid plist body")

    message_type = plist_data.get("MessageType")
    udid = plist_data.get("UDID")

    if message_type == "Authenticate":
        # Device is starting enrollment
        result = await db.execute(select(Device).where(Device.udid == udid))
        device = result.scalar_one_or_none()

        if not device:
            # New device enrolling - create placeholder (org to be assigned via token later)
            device = Device(
                udid=udid,
                platform=DevicePlatform.IOS,
                enrollment_type=EnrollmentType.MANUAL,
                status=DeviceStatus.PENDING,
                org_id="00000000-0000-0000-0000-000000000000",  # placeholder
            )
            db.add(device)
            await db.commit()

        return Response(status_code=200)

    elif message_type == "TokenUpdate":
        push_magic = plist_data.get("PushMagic")
        push_token_bytes = plist_data.get("Token")

        result = await db.execute(select(Device).where(Device.udid == udid))
        device = result.scalar_one_or_none()

        if device:
            if isinstance(push_token_bytes, bytes):
                device.push_token = push_token_bytes.hex()
            device.status = DeviceStatus.ENROLLED
            device.enrolled_at = datetime.utcnow()
            device.last_seen = datetime.utcnow()
            # Update device info from plist
            device.model = plist_data.get("ProductName") or device.model
            device.serial_number = plist_data.get("SerialNumber") or device.serial_number
            await db.commit()

        return Response(status_code=200)

    elif message_type == "CheckOut":
        result = await db.execute(select(Device).where(Device.udid == udid))
        device = result.scalar_one_or_none()
        if device:
            device.status = DeviceStatus.UNENROLLED
            device.checked_out = True
            await db.commit()

        return Response(status_code=200)

    # Unknown message type - acknowledge anyway
    return Response(status_code=200)


@router.put("/commands")
@router.post("/commands/{udid}")
async def apple_command_poll(request: Request, udid: Optional[str] = None, db: AsyncSession = Depends(get_db)):
    """
    Apple device polls for pending commands.
    Returns the next queued command in plist format.
    """
    body = await request.body()
    if body:
        try:
            plist_data = plistlib.loads(body)
            device_udid = plist_data.get("UDID") or udid
        except Exception:
            device_udid = udid
    else:
        device_udid = udid

    if not device_udid:
        return Response(status_code=200)

    # Update last_seen
    result = await db.execute(select(Device).where(Device.udid == device_udid))
    device = result.scalar_one_or_none()
    if device:
        device.last_seen = datetime.utcnow()
        await db.flush()

        # Get next pending command
        cmd_result = await db.execute(
            select(MDMCommand)
            .where(MDMCommand.device_id == device.id, MDMCommand.status == CommandStatus.QUEUED)
            .order_by(MDMCommand.created_at)
            .limit(1)
        )
        cmd = cmd_result.scalar_one_or_none()

        if cmd:
            # Build Apple MDM command plist
            command_payload = {
                "Command": {
                    "RequestType": cmd.command_type.value,
                    **(cmd.payload or {}),
                },
                "CommandUUID": cmd.id,
            }
            cmd.status = CommandStatus.SENT
            cmd.sent_at = datetime.utcnow()
            await db.commit()

            plist_data = plistlib.dumps(command_payload)
            return Response(content=plist_data, media_type="application/xml")

        await db.commit()

    # No pending commands
    return Response(status_code=200)


@router.post("/acknowledge")
async def apple_acknowledge(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Apple device acknowledges a command result.
    """
    body = await request.body()
    try:
        plist_data = plistlib.loads(body)
    except Exception:
        raise HTTPException(400, "Invalid plist")

    command_uuid = plist_data.get("CommandUUID")
    status_str = plist_data.get("Status")

    if command_uuid:
        result = await db.execute(select(MDMCommand).where(MDMCommand.id == command_uuid))
        cmd = result.scalar_one_or_none()
        if cmd:
            if status_str == "Acknowledged":
                cmd.status = CommandStatus.ACKNOWLEDGED
                cmd.acknowledged_at = datetime.utcnow()
                cmd.result = plist_data
            elif status_str == "Error":
                cmd.status = CommandStatus.ERROR
                cmd.error_message = plist_data.get("ErrorChain", [{}])[0].get("LocalizedDescription", "Unknown error")
            await db.commit()

    return Response(status_code=200)
