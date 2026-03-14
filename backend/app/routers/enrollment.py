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


@router.get("/package/windows/setup")
async def download_setup_exe():
    """
    Download the pre-built static Windows .exe installer.
    Generic (no token embedded) — IT admin enters token in the wizard.
    """
    import pathlib
    from fastapi.responses import Response as FastAPIResponse
    exe_path = pathlib.Path(__file__).parent.parent.parent / "scripts" / "NOCKO-MDM-Agent-Setup.exe"
    if not exe_path.exists():
        raise HTTPException(status_code=404, detail="Installer not found")
    return FastAPIResponse(
        content=exe_path.read_bytes(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": 'attachment; filename="NOCKO-MDM-Agent-Setup.exe"'},
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
    # __file__ = /app/app/routers/enrollment.py  → 3x parent = /app
    template_path = pathlib.Path(__file__).parent.parent.parent / "scripts" / "nocko-mdm-agent.ps1"
    if template_path.exists():
        template = template_path.read_text(encoding="utf-8")
    else:
        import logging
        logging.warning(f"PS1 template not found at: {template_path}")
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


@router.get("/package/windows/{token_id}/download-bat")
async def download_windows_bat(
    token_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Download a .bat launcher that:
    1. Downloads the PS1 agent script from this server
    2. Runs it with -ExecutionPolicy Bypass (bypasses Windows script restrictions)
    3. Passes -Install flag to register as a Scheduled Task
    No prerequisites needed — just double-click as Administrator.
    """
    result = await db.execute(
        select(EnrollmentToken).where(EnrollmentToken.id == token_id)
    )
    token = result.scalar_one_or_none()
    if not token:
        raise HTTPException(status_code=404, detail="Token not found")

    org_result = await db.execute(
        select(__import__("app.models.user", fromlist=["Organization"]).Organization)
        .where(__import__("app.models.user", fromlist=["Organization"]).Organization.id == token.org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "Unknown"
    safe_name = re.sub(r"[^a-z0-9-]", "-", org_name.lower()).strip("-")

    ps1_url = f"{settings.MDM_SERVER_URL}/api/v1/enrollment/package/windows/{token_id}/download"
    ps1_name = f"nocko-agent-{safe_name}.ps1"
    bat_name = f"install-nocko-{safe_name}.bat"

    bat_content = f"""@echo off
:: ============================================================
:: NOCKO MDM Agent Installer
:: Organization : {org_name}
:: MDM Server   : {settings.MDM_SERVER_URL}
:: ============================================================
:: Run this file as Administrator to install the NOCKO MDM agent.
:: It will download and execute the agent script automatically.

NET SESSION >nul 2>&1
IF %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Please run this file as Administrator.
    echo Right-click ^> Run as administrator
    pause
    exit /b 1
)

echo.
echo  NOCKO MDM Agent Installer
echo  Organization: {org_name}
echo  Server: {settings.MDM_SERVER_URL}
echo.

:: Download the PS1 script
set "PS1_URL={ps1_url}"
set "PS1_PATH=%TEMP%\\{ps1_name}"

echo [1/3] Downloading agent script...
powershell.exe -ExecutionPolicy Bypass -Command "Invoke-WebRequest -Uri '%PS1_URL%' -OutFile '%PS1_PATH%' -UseBasicParsing"

if not exist "%PS1_PATH%" (
    echo [ERROR] Download failed. Check your internet connection.
    pause
    exit /b 1
)

echo [2/3] Installing NOCKO MDM agent...
powershell.exe -ExecutionPolicy Bypass -File "%PS1_PATH%" -Install

echo [3/3] Done!
echo.
echo The NOCKO MDM agent has been installed and will run automatically.
echo Device will appear in the MDM dashboard within 1-2 minutes.
echo.
pause
"""

    from fastapi.responses import Response as FastAPIResponse
    return FastAPIResponse(
        content=bat_content.encode("utf-8"),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{bat_name}"'},
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


@router.get("/package/windows/{token_id}/download-exe")
async def download_windows_exe(
    token_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    Build and download a real Windows .exe installer using NSIS.
    Installs the MDM agent to C:\\ProgramData\\NOCKO-MDM and registers
    a SYSTEM scheduled task. Includes proper uninstaller.
    """
    import pathlib
    import subprocess
    import tempfile
    import shutil

    result = await db.execute(
        select(EnrollmentToken).where(EnrollmentToken.id == token_id)
    )
    token = result.scalar_one_or_none()
    if not token or not token.is_valid:
        raise HTTPException(status_code=404, detail="Package not found or expired")

    # Load org info
    org_result = await db.execute(
        select(__import__("app.models.user", fromlist=["Organization"]).Organization)
        .where(__import__("app.models.user", fromlist=["Organization"]).Organization.id == token.org_id)
    )
    org = org_result.scalar_one_or_none()
    org_name = org.name if org else "NOCKO"
    safe_name = re.sub(r"[^a-z0-9-]", "-", org_name.lower()).strip("-")

    # Load PS1 agent script
    base = pathlib.Path(__file__).parent.parent.parent
    ps1_path = base / "scripts" / "nocko-mdm-agent.ps1"
    if ps1_path.exists():
        ps1_content = ps1_path.read_text(encoding="utf-8")
    else:
        ps1_content = _minimal_agent_template()

    # Bake in server URL and token
    ps1_content = ps1_content.replace(
        "PASTE_ENROLLMENT_TOKEN_HERE", token.token
    ).replace(
        "https://mdm.it-uae.com/api/v1", settings.MDM_SERVER_URL
    ).replace(
        "http://localhost:8000/api/v1", settings.MDM_SERVER_URL
    )

    # Check if makensis is available
    nsis_available = shutil.which("makensis") is not None

    if not nsis_available:
        # Fallback: return a self-installing PowerShell script as .ps1
        import logging
        logging.warning("makensis not found — falling back to .ps1 download")
        from fastapi.responses import Response as FastAPIResponse
        return FastAPIResponse(
            content=ps1_content.encode("utf-8"),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="nocko-agent-{safe_name}.ps1"'},
        )

    # Load NSIS template
    nsi_template_path = base / "scripts" / "installer.nsi"
    if not nsi_template_path.exists():
        raise HTTPException(status_code=500, detail="NSIS template not found")

    nsi_template = nsi_template_path.read_text(encoding="utf-8")

    # Escape PS1 content for NSIS string embedding
    # NSIS FileWrite requires special escaping
    ps1_escaped = ps1_content.replace("\\", "\\\\").replace('"', '$\\"').replace("\r\n", "\\r\\n").replace("\n", "\\r\\n").replace("\t", "\\t")

    # Build NSIS script with injected values
    nsi_script = nsi_template.replace(
        "__PS1_CONTENT__", ps1_escaped
    ).replace(
        "__SERVER__", settings.MDM_SERVER_URL
    ).replace(
        "__ORG_NAME__", org_name
    ).replace(
        'OutFile "nocko-mdm-installer.exe"',
        f'OutFile "nocko-agent-{safe_name}.exe"'
    )

    # Build in a temp directory
    with tempfile.TemporaryDirectory() as tmpdir:
        nsi_file = pathlib.Path(tmpdir) / "installer.nsi"
        nsi_file.write_text(nsi_script, encoding="utf-8")

        exe_name = f"nocko-agent-{safe_name}.exe"
        exe_path = pathlib.Path(tmpdir) / exe_name

        try:
            result = subprocess.run(
                ["makensis", str(nsi_file)],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=tmpdir,
            )
            if result.returncode != 0:
                import logging
                logging.error(f"makensis failed:\n{result.stdout}\n{result.stderr}")
                raise HTTPException(status_code=500, detail=f"Build failed: {result.stderr[:500]}")
        except subprocess.TimeoutExpired:
            raise HTTPException(status_code=500, detail="Installer build timed out")

        if not exe_path.exists():
            raise HTTPException(status_code=500, detail="Installer file was not created")

        exe_bytes = exe_path.read_bytes()

    from fastapi.responses import Response as FastAPIResponse
    return FastAPIResponse(
        content=exe_bytes,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{exe_name}"'},
    )
