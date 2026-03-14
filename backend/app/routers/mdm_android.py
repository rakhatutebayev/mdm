"""
Android Enterprise EMM Router

Handles Android device enrollment and management callbacks.
Uses Android Management API (AMAPI) via Google service account.

Docs: https://developers.google.com/android/management
"""
import uuid
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.db import get_db
from app.models.device import Device, DevicePlatform, DeviceStatus, EnrollmentType
from app.models.enrollment import EnrollmentToken
from app.models.user import User, UserRole
from app.routers.auth import get_current_user, require_role
from app.services.android_emm import (
    create_enrollment_token as create_android_token,
    get_android_device_info,
)

router = APIRouter(prefix="/mdm/android", tags=["android-mdm"])


class AndroidEnrollmentResponse(BaseModel):
    enrollment_token: str
    qr_code_token: str
    enrollment_url: str
    expires_at: Optional[str]


@router.post("/enrollment-token", response_model=AndroidEnrollmentResponse)
async def generate_android_enrollment(
    is_byod: bool = False,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Generate an Android Enterprise enrollment token (Zero-Touch or QR code)."""
    token_data = await create_android_token(
        org_id=current_user.org_id,
        is_byod=is_byod
    )
    return AndroidEnrollmentResponse(**token_data)


@router.post("/webhook")
async def android_management_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Receive Android Management API Pub/Sub notifications.
    Register as a webhook in Google Cloud Pub/Sub to receive device lifecycle events.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON")

    # Android Management API Pub/Sub message format
    message = body.get("message", {})
    device_data = message.get("attributes", {})

    device_id = device_data.get("deviceId")
    enterprise_id = device_data.get("enterpriseId")
    event_type = device_data.get("eventType")

    if not device_id or not event_type:
        return {"status": "ignored"}

    result = await db.execute(select(Device).where(Device.android_id == device_id))
    device = result.scalar_one_or_none()

    if event_type == "ENROLLMENT_COMPLETE" and not device:
        device = Device(
            android_id=device_id,
            platform=DevicePlatform.ANDROID,
            enrollment_type=EnrollmentType.ANDROID_ENTERPRISE,
            status=DeviceStatus.ENROLLED,
            org_id="",  # Resolve by enterprise_id mapping
            enrolled_at=datetime.utcnow(),
            last_seen=datetime.utcnow(),
        )
        db.add(device)
        await db.commit()

    elif event_type == "DEVICE_UPDATED" and device:
        device.last_seen = datetime.utcnow()
        await db.commit()

    elif event_type in ("DEVICE_DELETED", "UNENROLLMENT_COMPLETE") and device:
        device.status = DeviceStatus.UNENROLLED
        await db.commit()

    return {"status": "ok"}
