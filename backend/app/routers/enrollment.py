"""
Enrollment Router — generates and validates enrollment tokens for BYOD and managed devices.
"""
import io
import re
import uuid
import qrcode
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, EmailStr

from app.db import get_db
from app.models.enrollment import EnrollmentToken, EnrollmentPlatform
from app.models.user import User, UserRole
from app.routers.auth import get_current_user, require_role
from app.config import get_settings

router = APIRouter(prefix="/enrollment", tags=["enrollment"])
settings = get_settings()


class CreateTokenRequest(BaseModel):
    platform: EnrollmentPlatform = EnrollmentPlatform.ANY
    is_byod: bool = False
    assigned_user_email: Optional[EmailStr] = None
    max_uses: int = 1
    expires_in_days: int = 7


class TokenOut(BaseModel):
    id: str
    token: str
    platform: EnrollmentPlatform
    is_byod: bool
    assigned_user_email: Optional[str]
    enrollment_url: str
    expires_at: datetime
    use_count: int
    max_uses: int
    is_valid: bool

    class Config:
        from_attributes = True


@router.post("/token", response_model=TokenOut, status_code=201)
async def create_enrollment_token(
    body: CreateTokenRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    token = EnrollmentToken(
        org_id=current_user.org_id,
        created_by=current_user.id,
        platform=body.platform,
        is_byod=body.is_byod,
        assigned_user_email=body.assigned_user_email,
        max_uses=body.max_uses,
        expires_at=datetime.utcnow() + timedelta(days=body.expires_in_days),
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    enrollment_url = f"{settings.MDM_SERVER_URL}/enroll/{token.token}"
    return TokenOut(
        **{
            "id": token.id,
            "token": token.token,
            "platform": token.platform,
            "is_byod": token.is_byod,
            "assigned_user_email": token.assigned_user_email,
            "enrollment_url": enrollment_url,
            "expires_at": token.expires_at,
            "use_count": token.use_count,
            "max_uses": token.max_uses,
            "is_valid": token.is_valid,
        }
    )


@router.get("/token", response_model=List[TokenOut])
async def list_tokens(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EnrollmentToken)
        .where(EnrollmentToken.org_id == current_user.org_id)
        .order_by(EnrollmentToken.created_at.desc())
        .limit(100)
    )
    tokens = result.scalars().all()
    return [
        TokenOut(
            id=t.id,
            token=t.token,
            platform=t.platform,
            is_byod=t.is_byod,
            assigned_user_email=t.assigned_user_email,
            enrollment_url=f"{settings.MDM_SERVER_URL}/enroll/{t.token}",
            expires_at=t.expires_at,
            use_count=t.use_count,
            max_uses=t.max_uses,
            is_valid=t.is_valid,
        )
        for t in tokens
    ]


@router.get("/token/{token}/qrcode")
async def get_qr_code(
    token: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return a PNG QR code for the enrollment URL."""
    result = await db.execute(
        select(EnrollmentToken).where(
            EnrollmentToken.token == token,
            EnrollmentToken.org_id == current_user.org_id,
        )
    )
    enrollment = result.scalar_one_or_none()
    if not enrollment:
        raise HTTPException(404, "Token not found")

    url = f"{settings.MDM_SERVER_URL}/enroll/{token}"
    img = qrcode.make(url)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    return Response(content=buf.read(), media_type="image/png")


@router.delete("/token/{token_id}")
async def revoke_token(
    token_id: str,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(EnrollmentToken).where(
            EnrollmentToken.id == token_id,
            EnrollmentToken.org_id == current_user.org_id,
        )
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(404, "Token not found")

    await db.delete(token)
    await db.commit()
    return {"message": "Token revoked"}


# ── Package Builder ──────────────────────────────────────────────────────────

class PackageCreateRequest(BaseModel):
    """Request to generate a Windows agent installer package for an organization."""
    org_id: str
    package_name: Optional[str] = None       # e.g. "Acme Corp Agent"
    max_uses: int = 0                         # 0 = unlimited
    expires_in_days: int = 0                  # 0 = never expires


class PackageOut(BaseModel):
    token_id: str
    token: str
    package_name: str
    org_id: str
    download_url: str
    oneliner: str
    expires_at: Optional[datetime]
    max_uses: int


@router.post("/package/windows", response_model=PackageOut, status_code=201)
async def create_windows_package(
    body: PackageCreateRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Package Builder — creates a dedicated enrollment token for the given
    organization and returns a download URL for a pre-configured .ps1 installer.

    SUPER_ADMIN can create packages for any org.
    ADMIN/IT_MANAGER can only create packages for their own org.
    """
    from app.models.user import Organization

    # Access control: non-super-admins scoped to own org
    if current_user.role != UserRole.SUPER_ADMIN:
        if body.org_id != str(current_user.org_id):
            raise HTTPException(status_code=403, detail="Cannot create package for another organization")

    # Validate org exists
    result = await db.execute(select(Organization).where(Organization.id == body.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    package_name = body.package_name or f"{org.name} Windows Agent"

    # Create a dedicated enrollment token
    expires_at = (
        datetime.utcnow() + timedelta(days=body.expires_in_days)
        if body.expires_in_days > 0 else None
    )
    token = EnrollmentToken(
        org_id=body.org_id,
        created_by=current_user.id,
        platform=EnrollmentPlatform.WINDOWS,
        is_byod=False,
        max_uses=body.max_uses if body.max_uses > 0 else 999_999,  # DB doesn't support null
        expires_at=expires_at or (datetime.utcnow() + timedelta(days=36500)),  # ~100 years
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    base_url = settings.MDM_SERVER_URL
    download_url = f"{base_url}/api/v1/enrollment/package/windows/{token.id}/download"
    oneliner = f"irm '{base_url}/api/v1/enrollment/package/windows/{token.id}/download' | iex"

    return PackageOut(
        token_id=str(token.id),
        token=token.token,
        package_name=package_name,
        org_id=body.org_id,
        download_url=download_url,
        oneliner=oneliner,
        expires_at=expires_at,
        max_uses=body.max_uses,
    )


@router.get("/package/windows/{token_id}/download")
async def download_windows_package(
    token_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Download the pre-configured Windows PowerShell agent installer.
    The .ps1 has MDM server URL and enrollment token baked in.
    No authentication required — the token itself is the secret.
    """
    from fastapi.responses import PlainTextResponse
    import pathlib

    result = await db.execute(
        select(EnrollmentToken).where(EnrollmentToken.id == token_id)
    )
    token = result.scalar_one_or_none()
    if not token or not token.is_valid:
        raise HTTPException(status_code=404, detail="Package not found or expired")

    # Load the agent template from scripts directory
    template_path = pathlib.Path(__file__).parent.parent.parent.parent / "scripts" / "nocko-mdm-agent.ps1"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        # Minimal fallback template
        template = _minimal_agent_template()

    # Bake in server URL and token
    script = template.replace(
        "PASTE_ENROLLMENT_TOKEN_HERE", token.token
    ).replace(
        "https://mdm.it-uae.com/api/v1", settings.MDM_SERVER_URL
    ).replace(
        "http://localhost:8000/api/v1", settings.MDM_SERVER_URL
    )

    # Org info comment header
    org_result = await db.execute(
        select(__import__("app.models.user", fromlist=["Organization"]).Organization)
        .where(__import__("app.models.user", fromlist=["Organization"]).Organization.id == token.org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Unknown"

    header = f"""# ============================================================
# NOCKO MDM Agent — Pre-configured Package
# Organization : {org_name}
# MDM Server   : {settings.MDM_SERVER_URL}
# Token        : {token.token}
# Generated    : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
# ============================================================
"""
    final_script = header + script

    # Get org name for filename
    safe_name = re.sub(r"[^a-z0-9-]", "-", org_name.lower()).strip("-")
    filename = f"nocko-agent-{safe_name}.ps1"

    from fastapi.responses import Response as FastAPIResponse
    return FastAPIResponse(
        content=final_script.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _minimal_agent_template() -> str:
    """Minimal agent template when the full .ps1 is not found."""
    return '''#Requires -Version 5.1
param([switch]$Install, [switch]$Uninstall, [switch]$CheckIn, [switch]$Status,
      [string]$Server = "", [string]$Token = "")

$MDM_SERVER       = if ($Server) { $Server } else { "https://mdm.it-uae.com/api/v1" }
$ENROLLMENT_TOKEN = if ($Token)  { $Token  } else { "PASTE_ENROLLMENT_TOKEN_HERE" }
$CHECK_IN_MINUTES = 15
$TASK_NAME        = "NOCKO-MDM-Agent"
$AGENT_DIR        = "$env:ProgramData\\NOCKO-MDM"
$LOG_FILE         = "$AGENT_DIR\\agent.log"

Write-Host "NOCKO MDM Agent"
Write-Host "Server: $MDM_SERVER"
Write-Host "Token: $ENROLLMENT_TOKEN"
Write-Host "Run with -Install to register as a scheduled task."
'''
