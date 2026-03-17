from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.request import urlopen
import hashlib

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Customer, EnrollmentToken
from package_builder.bootstrap_exe import embed_bootstrap_config
from package_builder import build_zip
from package_builder.release_catalog import find_artifact, load_release_catalog
from routers.settings import get_agent_package_settings, get_server_url

router = APIRouter(prefix="/api/v1/packages", tags=["packages"])

# ── Artifact cache ───────────────────────────────────────────────────────────
_CACHE_DIR = Path("/tmp/nocko_agent_cache")
_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _download_or_cache(url: str, sha256_expected: str | None, fmt: str) -> bytes:
    """Download artifact from URL, caching by SHA256 on disk.

    First call downloads 13 MB; subsequent calls read from /tmp cache.
    Cache entry is keyed by url-derived hash to avoid collisions.
    """
    url_key = hashlib.md5(url.encode()).hexdigest()[:16]
    cache_file = _CACHE_DIR / f"{url_key}.bin"

    if cache_file.exists():
        data = cache_file.read_bytes()
        # Verify cached file integrity if we have expected sha256
        if sha256_expected:
            actual = hashlib.sha256(data).hexdigest()
            if actual == sha256_expected:
                return data
            # sha256 mismatch → stale cache, re-download
            cache_file.unlink(missing_ok=True)

    # Download from remote
    try:
        with urlopen(url, timeout=60) as remote:
            data = remote.read()
    except URLError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Could not download prebuilt {fmt.upper()} artifact: {e.reason}",
        ) from e

    # Save to cache
    try:
        cache_file.write_bytes(data)
    except OSError:
        pass  # cache write failure is non-fatal

    return data



class PackageRequest(BaseModel):
    customer_id: str          # UUID or slug
    format: str               # "zip" | "exe" | "msi"
    arch: str = "x64"         # "x64" | "x86"
    server_url: Optional[str] = None   # override if needed
    install_mode: str = "silent"       # "silent" | "interactive"
    agent_display_name: str = "NOCKO MDM Agent"
    install_dir: str = r"C:\Program Files\NOCKO MDM\Agent"
    log_dir: str = r"C:\ProgramData\NOCKO MDM\logs"
    register_scheduled_task: bool = True
    start_immediately: bool = True


class PackageArtifact(BaseModel):
    format: str
    arch: str
    version: str
    filename: str
    download_url: str
    sha256: Optional[str] = None
    size_bytes: Optional[int] = None
    notes: Optional[str] = None


class PackageCatalogOut(BaseModel):
    customer_id: str
    customer_name: str
    server_url: str
    enrollment_token: str
    release_channel: str
    release_version: Optional[str] = None
    generated_at: Optional[str] = None
    artifacts: list[PackageArtifact]
    bootstrap_formats: list[str]


def _as_bool(value: str) -> bool:
    return str(value).strip().lower() == "true"


async def _resolve_customer_and_token(customer_id: str, db: AsyncSession) -> tuple[Customer, EnrollmentToken]:
    """Resolve customer and its most recent active token."""

    cust_result = await db.execute(
        select(Customer).where(
            (Customer.id == customer_id) | (Customer.slug == customer_id)
        )
    )
    customer: Customer | None = cust_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # ── Get enrollment token ──────────────────────────────────────────────────
    token_result = await db.execute(
        select(EnrollmentToken)
        .where(
            EnrollmentToken.customer_id == customer.id,
            EnrollmentToken.revoked == False,  # noqa: E712
        )
        .order_by(EnrollmentToken.created_at.desc())
    )
    token_row = token_result.scalars().first()
    if not token_row:
        raise HTTPException(status_code=404, detail="No active enrollment token found. Generate one first.")

    return customer, token_row


@router.get("/catalog", response_model=PackageCatalogOut)
async def get_package_catalog(customer_id: str, db: AsyncSession = Depends(get_db)):
    """Return the latest prebuilt agent artifacts plus enrollment metadata."""
    customer, token_row = await _resolve_customer_and_token(customer_id, db)
    server_url = (await get_server_url(db)).rstrip("/")
    catalog = load_release_catalog()
    latest_release = catalog["releases"][0] if catalog["releases"] else None

    artifacts: list[PackageArtifact] = []
    if latest_release:
        version = str(latest_release.get("version", "unknown"))
        for artifact in latest_release.get("artifacts", []):
            url = artifact.get("url")
            filename = artifact.get("filename")
            fmt = artifact.get("format")
            arch = artifact.get("arch")
            if not all([url, filename, fmt, arch]):
                continue

            artifacts.append(
                PackageArtifact(
                    format=str(fmt),
                    arch=str(arch),
                    version=version,
                    filename=str(filename),
                    download_url=str(url),
                    sha256=artifact.get("sha256"),
                    size_bytes=artifact.get("size_bytes"),
                    notes=artifact.get("notes"),
                )
            )

    return PackageCatalogOut(
        customer_id=str(customer.id),
        customer_name=customer.name,
        server_url=server_url,
        enrollment_token=token_row.token,
        release_channel=str(catalog.get("channel", "stable")),
        release_version=(str(latest_release.get("version")) if latest_release else None),
        generated_at=catalog.get("generated_at"),
        artifacts=artifacts,
        bootstrap_formats=["exe", "zip"],
    )


@router.post("/generate")
async def generate_package(body: PackageRequest, db: AsyncSession = Depends(get_db)):
    """Return a ZIP bootstrap package or proxy a prebuilt MSI/EXE release artifact."""
    customer, token_row = await _resolve_customer_and_token(body.customer_id, db)
    package_settings = await get_agent_package_settings(db)
    server_url = (body.server_url or package_settings["server_url"]).rstrip("/")

    kwargs = dict(
        customer_id=str(customer.id),
        customer_name=customer.name,
        enrollment_token=token_row.token,
        server_url=server_url,
        arch=body.arch,
        install_mode=body.install_mode.lower(),
        agent_display_name=body.agent_display_name,
        install_dir=body.install_dir,
        log_dir=body.log_dir,
        register_scheduled_task=body.register_scheduled_task,
        start_immediately=body.start_immediately,
        heartbeat_interval=int(package_settings["heartbeat_interval"]),
        metrics_interval=int(package_settings["metrics_interval"]),
        inventory_interval=int(package_settings["inventory_interval"]),
        commands_interval=int(package_settings["commands_interval"]),
        log_level=package_settings["log_level"],
        siem_enabled=_as_bool(package_settings["siem_enabled"]),
    )

    fmt = body.format.lower()

    # Resolve artifact version up-front so bootstrap_config carries it
    _catalog_release, _catalog_artifact = find_artifact(fmt if fmt in {"exe", "msi"} else "exe", body.arch)
    _agent_version = str(_catalog_release.get("version", "")) if _catalog_release else ""

    # Derive MQTT host from server_url (same hostname, port 1883)
    _mqtt_host = server_url.replace("https://", "").replace("http://", "").split("/")[0]

    bootstrap_config = {
        "server_url": server_url,
        "enrollment_token": token_row.token,
        "customer_id": str(customer.id),
        "heartbeat_interval": int(package_settings["heartbeat_interval"]),
        "metrics_interval": int(package_settings["metrics_interval"]),
        "inventory_interval": int(package_settings["inventory_interval"]),
        "commands_interval": int(package_settings["commands_interval"]),
        "mdm_enabled": True,
        "siem_enabled": _as_bool(package_settings["siem_enabled"]),
        "backup_enabled": False,
        "remote_enabled": False,
        "log_level": package_settings["log_level"],
        "agent_version": _agent_version,   # ← real version from manifest
        "device_id": "",
        "install_dir": body.install_dir,
        "log_dir": body.log_dir,
        "start_immediately": body.start_immediately,
        "agent_display_name": body.agent_display_name,
        # MQTT — instant command delivery via WebSocket over HTTPS (no extra ports needed)
        "mqtt_enabled":   True,
        "mqtt_host":      _mqtt_host,
        "mqtt_port":      443,
        "mqtt_transport": "websockets",
        "mqtt_path":      "/mqtt",
        "mqtt_tls":       True,
    }

    # ── Build package ─────────────────────────────────────────────────────────
    try:
        if fmt == "zip":
            data      = build_zip(**kwargs)
            mime      = "application/zip"
            filename  = f"nocko-mdm-bootstrap-{customer.slug}-{_agent_version or 'latest'}.zip"

        elif fmt in {"exe", "msi"}:
            release, artifact = find_artifact(fmt, body.arch)
            if not release or not artifact:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        f"No prebuilt {fmt.upper()} artifact is configured for arch '{body.arch}'. "
                        "Publish a Windows agent release from GitHub Actions to update "
                        "backend/package_builder/agent_releases.json."
                    ),
                )

            data = _download_or_cache(
                url=str(artifact["url"]),
                sha256_expected=artifact.get("sha256"),
                fmt=fmt,
            )

            if fmt == "exe":
                data = embed_bootstrap_config(data, bootstrap_config)
                filename = f"nocko-mdm-agent-{customer.slug}-{_agent_version or release.get('version', 'latest')}.exe"
            else:
                filename = str(artifact.get("filename") or f"nocko-mdm-agent.{fmt}")

            mime = "application/octet-stream"

        else:
            raise HTTPException(status_code=400, detail=f"Unknown format '{fmt}'. Use: zip, exe, msi")

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Package build failed: {e}")

    return Response(
        content=data,
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
