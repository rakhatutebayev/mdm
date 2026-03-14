"""
Apps Router — Manage corporate app catalog and push apps to devices.
"""
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from datetime import datetime

from app.db import get_db
from app.models.app_catalog import AppCatalog
from app.models.device import Device, DevicePlatform, DeviceStatus
from app.models.command import MDMCommand, CommandType
from app.models.user import User, UserRole
from app.routers.auth import get_current_user, require_role
from app.services.apple_mdm import send_apple_push
from app.services.android_emm import send_android_command

router = APIRouter(prefix="/apps", tags=["apps"])


class AppIn(BaseModel):
    name: str
    bundle_id: str
    app_store_id: Optional[str] = None
    play_store_url: Optional[str] = None
    icon_url: Optional[str] = None
    version: Optional[str] = None
    is_managed: bool = True
    is_byod_allowed: bool = False
    description: Optional[str] = None


class AppOut(BaseModel):
    id: str
    name: str
    bundle_id: str
    app_store_id: Optional[str]
    play_store_url: Optional[str]
    icon_url: Optional[str]
    version: Optional[str]
    is_managed: bool
    is_byod_allowed: bool
    description: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


class PushAppRequest(BaseModel):
    app_id: str
    device_ids: List[str]


@router.get("", response_model=List[AppOut])
async def list_apps(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AppCatalog).where(AppCatalog.org_id == current_user.org_id).order_by(AppCatalog.name)
    )
    return result.scalars().all()


@router.post("", response_model=AppOut, status_code=201)
async def create_app(
    body: AppIn,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    app = AppCatalog(org_id=current_user.org_id, **body.model_dump())
    db.add(app)
    await db.commit()
    await db.refresh(app)
    return app


@router.delete("/{app_id}")
async def delete_app(
    app_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AppCatalog).where(AppCatalog.id == app_id, AppCatalog.org_id == current_user.org_id)
    )
    app = result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "App not found")
    await db.delete(app)
    await db.commit()
    return {"message": "App removed from catalog"}


@router.post("/push")
async def push_app_to_devices(
    body: PushAppRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """Push an app from the catalog to one or more enrolled devices."""
    app_result = await db.execute(
        select(AppCatalog).where(AppCatalog.id == body.app_id, AppCatalog.org_id == current_user.org_id)
    )
    app = app_result.scalar_one_or_none()
    if not app:
        raise HTTPException(404, "App not found in catalog")

    results = []
    for device_id in body.device_ids:
        dev_result = await db.execute(
            select(Device).where(Device.id == device_id, Device.org_id == current_user.org_id)
        )
        device = dev_result.scalar_one_or_none()
        if not device or device.status not in [DeviceStatus.ENROLLED, DeviceStatus.SUPERVISED]:
            results.append({"device_id": device_id, "status": "skipped", "reason": "not enrolled"})
            continue

        if device.platform in [DevicePlatform.IOS, DevicePlatform.IPADOS, DevicePlatform.MACOS]:
            cmd = MDMCommand(
                device_id=device.id,
                issued_by=current_user.id,
                command_type=CommandType.INSTALL_APP,
                payload={
                    "ManifestURL": f"https://itunes.apple.com/app/id{app.app_store_id}" if app.app_store_id else "",
                    "iTunesStoreID": int(app.app_store_id) if app.app_store_id else None,
                    "Identifier": app.bundle_id,
                },
            )
            db.add(cmd)
            await db.flush()
            await send_apple_push(device.push_token)

        elif device.platform == DevicePlatform.ANDROID:
            await send_android_command(device, CommandType.ANDROID_INSTALL_APP, {
                "packageName": app.bundle_id,
                "playStoreUrl": app.play_store_url,
            })

        results.append({"device_id": device_id, "status": "queued"})

    await db.commit()
    return {"results": results}
