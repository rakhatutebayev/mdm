"""
Agent Package Router — NOCKO MDM
Manages the base agent executable and generates org-specific installer packages.

Flow:
  1. SUPER_ADMIN uploads NOCKO-Agent-Setup.exe (built once with PyInstaller + Inno Setup)
  2. Admin uses Package Builder → gets a ZIP with:
       - NOCKO-Agent-Setup.exe  (the real installer)
       - nocko-config.json      (org token + server url)
       - install-silent.bat     (double-click to install)
       - README.txt             (instructions)
     OR a standalone setup.exe injected with config (if toolchain available)
"""
import io
import json
import re
import uuid
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response as FileResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_db
from app.models.enrollment import EnrollmentPlatform, EnrollmentToken
from app.models.user import Organization, User, UserRole
from app.routers.auth import get_current_user, require_role

router = APIRouter(prefix="/agent-packages", tags=["agent-packages"])
settings = get_settings()

# Where agent binaries are stored on the server
AGENT_STORE = Path("/var/nocko/agent-binaries")
AGENT_EXE_NAME = "NOCKO-Agent-Setup.exe"


def _agent_exe_path() -> Path:
    return AGENT_STORE / AGENT_EXE_NAME


def _has_agent_exe() -> bool:
    return _agent_exe_path().exists()


# ── Schemas ──────────────────────────────────────────────────────────────────

class PackageBuildRequest(BaseModel):
    org_id: str
    package_name: Optional[str] = None
    max_uses: int = 0           # 0 = unlimited
    expires_in_days: int = 0    # 0 = never


class AgentExeStatus(BaseModel):
    available: bool
    size_mb: Optional[float] = None
    uploaded_at: Optional[str] = None
    version: Optional[str] = None


# ── Upload base exe (SUPER_ADMIN only) ───────────────────────────────────────

@router.get("/exe-status", response_model=AgentExeStatus)
async def get_exe_status(
    current_user: User = Depends(get_current_user),
):
    """Check whether a pre-built agent installer is available on the server."""
    exe = _agent_exe_path()
    if not exe.exists():
        return AgentExeStatus(available=False)
    stat = exe.stat()
    return AgentExeStatus(
        available=True,
        size_mb=round(stat.st_size / 1_048_576, 1),
        uploaded_at=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M UTC"),
        version=settings.APP_VERSION,
    )


@router.post("/upload-exe", status_code=status.HTTP_201_CREATED)
async def upload_agent_exe(
    file: UploadFile = File(...),
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Upload the pre-built NOCKO-Agent-Setup.exe. SUPER_ADMIN only."""
    if not file.filename or not file.filename.lower().endswith(".exe"):
        raise HTTPException(status_code=400, detail="Only .exe files are accepted")

    AGENT_STORE.mkdir(parents=True, exist_ok=True)
    content = await file.read()
    if len(content) < 1024:
        raise HTTPException(status_code=400, detail="File too small — is it a valid EXE?")

    _agent_exe_path().write_bytes(content)
    size_mb = round(len(content) / 1_048_576, 1)
    return {"message": f"Agent EXE uploaded ({size_mb} MB)", "size_mb": size_mb}


# ── Trigger cross-compile build on Linux ─────────────────────────────────────

import asyncio
import subprocess
import threading

_build_lock = threading.Lock()
_build_status: dict = {"running": False, "last_result": None, "last_run": None}


class BuildStatus(BaseModel):
    running: bool
    available: bool
    last_result: Optional[str] = None
    last_run: Optional[str] = None
    size_mb: Optional[float] = None


@router.get("/build-exe/status", response_model=BuildStatus)
async def get_build_status(
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """Get the status of the cross-compile build pipeline."""
    exe = _agent_exe_path()
    return BuildStatus(
        running=_build_status["running"],
        available=exe.exists(),
        last_result=_build_status.get("last_result"),
        last_run=_build_status.get("last_run"),
        size_mb=round(exe.stat().st_size / 1_048_576, 1) if exe.exists() else None,
    )


@router.post("/build-exe", status_code=status.HTTP_202_ACCEPTED)
async def trigger_build_exe(
    current_user: User = Depends(require_role(UserRole.SUPER_ADMIN)),
):
    """
    Trigger the Linux→Windows cross-compilation pipeline.

    Uses Docker + Wine (cdrx/pyinstaller-windows image) to build
    NOCKO-Agent-Setup.exe on the Linux server without needing a Windows machine.

    The build runs in the background. Poll /build-exe/status for progress.
    Requires Docker to be accessible from the server process.
    """
    if _build_status["running"]:
        raise HTTPException(status_code=409, detail="Build already in progress")

    # Find the build script
    import pathlib
    project_root = pathlib.Path(__file__).parent.parent.parent.parent
    build_script = project_root / "build-agent.sh"
    agent_dir    = project_root / "agent-gui"

    if not build_script.exists():
        raise HTTPException(
            status_code=500,
            detail="build-agent.sh not found. Ensure the project is fully deployed."
        )

    def _run_build():
        _build_status["running"] = True
        _build_status["last_run"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        _build_status["last_result"] = "running"
        try:
            result = subprocess.run(
                ["bash", str(build_script)],
                cwd=str(project_root),
                capture_output=True, text=True, timeout=1800  # 30 min timeout
            )
            if result.returncode == 0:
                _build_status["last_result"] = "success"
            else:
                _build_status["last_result"] = f"failed: {result.stderr[-300:]}"
        except subprocess.TimeoutExpired:
            _build_status["last_result"] = "failed: timeout (30 min)"
        except Exception as e:
            _build_status["last_result"] = f"failed: {e}"
        finally:
            _build_status["running"] = False

    # Run in background thread (non-blocking)
    thread = threading.Thread(target=_run_build, daemon=True, name="agent-build")
    thread.start()

    return {
        "message": "Build started. Using Docker + Wine to cross-compile Windows EXE on Linux.",
        "poll_url": "/api/v1/agent-packages/build-exe/status",
        "estimated_time": "10-20 minutes on first run (Docker image pull + compile)",
    }


# ── Build org-specific package ────────────────────────────────────────────────

@router.post("/build")
async def build_package(
    body: PackageBuildRequest,
    current_user: User = Depends(require_role(UserRole.ADMIN, UserRole.IT_MANAGER, UserRole.SUPER_ADMIN)),
    db: AsyncSession = Depends(get_db),
):
    """
    Generate an org-specific installer package.
    Returns a ZIP file containing the agent exe + config + install scripts.
    """
    # Access control
    if current_user.role != UserRole.SUPER_ADMIN:
        if body.org_id != str(current_user.org_id):
            raise HTTPException(status_code=403, detail="Access denied")

    # Validate org
    result = await db.execute(select(Organization).where(Organization.id == body.org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=404, detail="Organization not found")

    # Create enrollment token
    expires_at = (
        datetime.utcnow() + timedelta(days=body.expires_in_days)
        if body.expires_in_days > 0
        else datetime.utcnow() + timedelta(days=36500)
    )
    token = EnrollmentToken(
        org_id=body.org_id,
        created_by=current_user.id,
        platform=EnrollmentPlatform.WINDOWS,
        is_byod=False,
        max_uses=body.max_uses if body.max_uses > 0 else 999_999,
        expires_at=expires_at,
    )
    db.add(token)
    await db.commit()
    await db.refresh(token)

    package_name = body.package_name or f"{org.name} Agent"
    safe_org = re.sub(r"[^a-z0-9-]", "-", org.name.lower()).strip("-")
    zip_filename = f"nocko-agent-{safe_org}.zip"

    # Build the config that will be bundled
    config = {
        "server_host":       settings.MDM_SERVER_URL.replace("https://", "").replace("http://", "").split("/")[0],
        "server_scheme":     "https" if settings.MDM_SERVER_URL.startswith("https") else "http",
        "api_prefix":        "/api/v1",
        "enrollment_token":  token.token,
        "organization":      org.name,
        "org_id":            str(org.id),
        "checkin_interval":  15,
        "siem_enabled":      True,
        "agent_version":     settings.APP_VERSION,
        "_generated_at":     datetime.utcnow().isoformat(),
        "_package_name":     package_name,
    }

    # Build ZIP in memory
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:

        # 1. nocko-config.json — the pre-configured settings file
        zf.writestr(
            f"{package_name}/nocko-config.json",
            json.dumps(config, indent=2, ensure_ascii=False)
        )

        # 2. install-silent.bat — double-click installer
        bat = _make_install_bat(package_name, settings.MDM_SERVER_URL, token.token)
        zf.writestr(f"{package_name}/install-silent.bat", bat)

        # 3. install.ps1 — PowerShell installer (copies config, runs setup)
        ps1 = _make_install_ps1(package_name, settings.MDM_SERVER_URL, token.token, org.name)
        zf.writestr(f"{package_name}/install.ps1", ps1)

        # 4. README.txt
        readme = _make_readme(package_name, org.name, settings.MDM_SERVER_URL, token.token)
        zf.writestr(f"{package_name}/README.txt", readme)

        # 5. Include the agent EXE if available
        if _has_agent_exe():
            zf.write(_agent_exe_path(), f"{package_name}/{AGENT_EXE_NAME}")
        else:
            # Add a notice file instead
            zf.writestr(
                f"{package_name}/AGENT-EXE-NOT-BUNDLED.txt",
                "The NOCKO-Agent-Setup.exe is not bundled in this package.\n"
                "Download it from your MDM dashboard and place it in this folder.\n"
                "Then run install-silent.bat as Administrator.\n\n"
                "Alternatively, use the PowerShell one-liner from the MDM dashboard.\n"
            )

    buf.seek(0)
    return FileResponse(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{zip_filename}"'},
    )


# ── Template generators ───────────────────────────────────────────────────────

def _make_install_bat(package_name: str, server: str, token: str) -> str:
    return f"""@echo off
REM ============================================================
REM  NOCKO MDM Agent — Silent Installer
REM  Package : {package_name}
REM  Server  : {server}
REM ============================================================
echo Installing NOCKO MDM Agent...

NET SESSION >NUL 2>&1 || (
    echo ERROR: Please run this file as Administrator!
    pause
    exit /B 1
)

REM Copy pre-configured config
if not exist "%ProgramData%\\NOCKO-Agent" mkdir "%ProgramData%\\NOCKO-Agent"
copy /Y "nocko-config.json" "%ProgramData%\\NOCKO-Agent\\config.json"

REM Run the installer
if exist "NOCKO-Agent-Setup.exe" (
    start /WAIT NOCKO-Agent-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
    echo.
    echo Installation complete!
    echo The NOCKO MDM Agent is now running in the system tray.
) else (
    echo.
    echo NOCKO-Agent-Setup.exe not found in this folder.
    echo Please download it from your MDM dashboard and re-run.
)
pause
"""


def _make_install_ps1(package_name: str, server: str, token: str, org: str) -> str:
    return f"""#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    NOCKO MDM Agent — Silent Installer
    Package     : {package_name}
    Organization: {org}
    Server      : {server}
.DESCRIPTION
    Installs the NOCKO MDM agent and pre-configures it for this organization.
    Run as Administrator.
#>
[CmdletBinding()]
param(
    [switch]$Uninstall
)

$ErrorActionPreference = 'Stop'
$Config = @{{
    server_host      = "{server.replace('https://', '').replace('http://', '').split('/')[0]}"
    server_scheme    = "{'https' if server.startswith('https') else 'http'}"
    api_prefix       = "/api/v1"
    enrollment_token = "{token}"
    checkin_interval = 15
    siem_enabled     = $true
    backup_enabled   = $false
    remote_enabled   = $false
    agent_version    = "1.0.0"
    organization     = "{org}"
}} | ConvertTo-Json

$ConfigDir = "$Env:ProgramData\\NOCKO-Agent"

if ($Uninstall) {{
    Write-Host "Removing NOCKO Agent..."
    $uninstaller = (Get-ItemProperty "HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\*" |
        Where-Object {{ $_.DisplayName -like "NOCKO*" }}).UninstallString
    if ($uninstaller) {{
        Start-Process -FilePath $uninstaller -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES" -Wait
    }}
    Remove-Item -Path $ConfigDir -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "Uninstalled."
    return
}}

# 1. Write pre-configured config
Write-Host "[1/3] Writing configuration..."
New-Item -ItemType Directory -Path $ConfigDir -Force | Out-Null
$Config | Set-Content "$ConfigDir\\config.json" -Encoding UTF8
Write-Host "      Config saved to $ConfigDir\\config.json"

# 2. Run installer
$Exe = Join-Path $PSScriptRoot "NOCKO-Agent-Setup.exe"
if (Test-Path $Exe) {{
    Write-Host "[2/3] Installing NOCKO Agent..."
    Start-Process -FilePath $Exe -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART" -Wait
}} else {{
    Write-Warning "[2/3] NOCKO-Agent-Setup.exe not found. Download from MDM dashboard."
}}

# 3. Start tray application
Write-Host "[3/3] Starting agent..."
$AgentExe = "$Env:ProgramFiles\\NOCKO-Agent\\NOCKO-Agent.exe"
if (Test-Path $AgentExe) {{
    Start-Process -FilePath $AgentExe
    Write-Host "Done! The agent is running in the system tray."
}} else {{
    Write-Host "Installation complete. Run NOCKO-Agent.exe to start."
}}
"""


def _make_readme(package_name: str, org: str, server: str, token: str) -> str:
    return f"""NOCKO MDM Agent — Installation Package
=======================================
Package     : {package_name}
Organization: {org}
Server      : {server}
Generated   : {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}

CONTENTS
--------
  NOCKO-Agent-Setup.exe   Windows agent installer (if bundled)
  nocko-config.json       Pre-configured settings for {org}
  install-silent.bat      Double-click installer (Run as Admin)
  install.ps1             PowerShell installer script
  README.txt              This file

INSTALLATION (Option 1 — Double-click)
---------------------------------------
  1. Right-click install-silent.bat → "Run as Administrator"
  2. Wait for installation to complete
  3. The agent icon will appear in your system tray ✓

INSTALLATION (Option 2 — PowerShell)
--------------------------------------
  Open PowerShell as Administrator, then run:
  
  cd <path-to-this-folder>
  Set-ExecutionPolicy Bypass -Scope Process -Force
  .\\install.ps1

INSTALLATION (Option 3 — Remote One-liner)
-------------------------------------------
  Deploy from PowerShell (no files needed):
  
  irm '{server}/api/v1/enrollment/package/windows/{{}}/download' | iex

DEPLOYMENT VIA GROUP POLICY / SCCM
-------------------------------------
  Silent install command:
  NOCKO-Agent-Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART
  
  Copy nocko-config.json to:
  %ProgramData%\\NOCKO-Agent\\config.json
  before or after installation.

SUPPORT
-------
  NOCKO MDM Dashboard: {server.replace('/api/v1', '')}
  Token (do not share): {token[:8]}...

"""
