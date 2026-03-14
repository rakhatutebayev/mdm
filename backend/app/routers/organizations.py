"""
Organizations Router — NOCKO MDM
SUPER_ADMIN: full CRUD across all orgs
ADMIN/IT_MANAGER: read-only access to their own org
"""
import uuid
import re
from datetime import datetime
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from pydantic import BaseModel, validator

from app.db import get_db
from app.models.user import Organization, User, UserRole
from app.models.device import Device
from app.models.enrollment import EnrollmentToken
from app.routers.auth import get_current_user, require_role

router = APIRouter(prefix="/organizations", tags=["organizations"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class OrgCreate(BaseModel):
    name: str
    domain: Optional[str] = None
    slug: Optional[str] = None
    max_devices: int = 0  # 0 = unlimited

    @validator("slug", pre=True, always=True)
    def auto_slug(cls, v, values):
        if v:
            return re.sub(r"[^a-z0-9-]", "-", v.lower()).strip("-")
        name = values.get("name", "org")
        return re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")


class OrgUpdate(BaseModel):
    name: Optional[str] = None
    domain: Optional[str] = None
    is_active: Optional[bool] = None
    max_devices: Optional[int] = None


class OrgOut(BaseModel):
    id: str
    name: str
    domain: Optional[str]
    slug: Optional[str]
    is_active: bool
    created_at: datetime
    max_devices: int = 0
    device_count: int = 0
    user_count: int = 0
    token_count: int = 0

    class Config:
        from_attributes = True


class OrgStats(BaseModel):
    device_count: int
    user_count: int
    token_count: int
    active_devices: int


# ── Helpers ─────────────────────────────────────────────────────────────────

async def _get_org_counts(db: AsyncSession, org_id: str) -> dict:
    dev_count = await db.scalar(
        select(func.count()).where(Device.org_id == org_id)
    )
    usr_count = await db.scalar(
        select(func.count()).where(User.org_id == org_id)
    )
    tok_count = await db.scalar(
        select(func.count()).where(EnrollmentToken.org_id == org_id)
    )
    return {
        "device_count": dev_count or 0,
        "user_count":   usr_count or 0,
        "token_count":  tok_count or 0,
    }


def _org_to_out(org: Organization, counts: dict) -> OrgOut:
    return OrgOut(
        id=str(org.id),
        name=org.name,
        domain=org.domain,
        slug=getattr(org, "slug", None),
        is_active=org.is_active,
        created_at=org.created_at,
        max_devices=getattr(org, "max_devices", 0) or 0,
        **counts,
    )


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[OrgOut])
async def list_organizations(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SUPER_ADMIN sees all orgs. Others see only their own."""
    if current_user.role == UserRole.SUPER_ADMIN:
        result = await db.execute(select(Organization).order_by(Organization.name))
        orgs = result.scalars().all()
    else:
        result = await db.execute(
            select(Organization).where(Organization.id == current_user.org_id)
        )
        orgs = result.scalars().all()

    out = []
    for org in orgs:
        counts = await _get_org_counts(db, str(org.id))
        out.append(_org_to_out(org, counts))
    return out


@router.post("", response_model=OrgOut, status_code=status.HTTP_201_CREATED)
async def create_organization(
    body: OrgCreate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """SUPER_ADMIN only: create a new organization."""
    org = Organization(
        id=str(uuid.uuid4()),
        name=body.name,
        domain=body.domain,
    )
    # Set optional extended fields if column exists
    if hasattr(org, "slug"):        org.slug        = body.slug
    if hasattr(org, "max_devices"): org.max_devices = body.max_devices
    db.add(org)
    await db.commit()
    await db.refresh(org)
    counts = await _get_org_counts(db, str(org.id))
    return _org_to_out(org, counts)


@router.get("/{org_id}", response_model=OrgOut)
async def get_organization(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    # Non-super-admins can only see their own org
    if current_user.role != UserRole.SUPER_ADMIN and str(org.id) != str(current_user.org_id):
        raise HTTPException(status_code=403, detail="Access denied")
    counts = await _get_org_counts(db, str(org.id))
    return _org_to_out(org, counts)


@router.patch("/{org_id}", response_model=OrgOut)
async def update_organization(
    org_id: str,
    body: OrgUpdate,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    if body.name       is not None: org.name       = body.name
    if body.domain     is not None: org.domain     = body.domain
    if body.is_active  is not None: org.is_active  = body.is_active
    if body.max_devices is not None and hasattr(org, "max_devices"):
        org.max_devices = body.max_devices
    await db.commit()
    await db.refresh(org)
    counts = await _get_org_counts(db, str(org.id))
    return _org_to_out(org, counts)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    org_id: str,
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Organization).where(Organization.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")
    await db.delete(org)
    await db.commit()


@router.get("/{org_id}/stats", response_model=OrgStats)
async def org_stats(
    org_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != UserRole.SUPER_ADMIN and str(current_user.org_id) != org_id:
        raise HTTPException(status_code=403, detail="Access denied")
    counts = await _get_org_counts(db, org_id)
    # Active devices (last seen within 1 hour)
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=1)
    active = await db.scalar(
        select(func.count()).where(
            Device.org_id == org_id,
            Device.last_seen >= cutoff,
        )
    )
    return OrgStats(active_devices=active or 0, **counts)
