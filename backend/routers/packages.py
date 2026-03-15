"""Packages router — generates agent installer packages for download."""
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Customer, EnrollmentToken
from package_builder import build_zip
from package_builder.exe_builder import build_exe, BuildToolMissingError as EXEMissing
from package_builder.msi_builder import build_msi, BuildToolMissingError as MSIMissing
from routers.settings import get_server_url

router = APIRouter(prefix="/api/v1/packages", tags=["packages"])


class PackageRequest(BaseModel):
    customer_id: str          # UUID or slug
    format: str               # "zip" | "exe" | "msi"
    arch: str = "x64"         # "x64" | "x86"
    server_url: Optional[str] = None   # override if needed


@router.post("/generate")
async def generate_package(body: PackageRequest, db: AsyncSession = Depends(get_db)):
    """Generate and return a Windows agent installer package."""

    # ── Resolve customer ──────────────────────────────────────────────────────
    cust_result = await db.execute(
        select(Customer).where(
            (Customer.id == body.customer_id) | (Customer.slug == body.customer_id)
        )
    )
    customer: Customer | None = cust_result.scalar_one_or_none()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found")

    # ── Get enrollment token ──────────────────────────────────────────────────
    token_result = await db.execute(
        select(EnrollmentToken)
        .where(EnrollmentToken.customer_id == customer.id)
        .order_by(EnrollmentToken.created_at.desc())
    )
    token_row = token_result.scalars().first()
    if not token_row:
        raise HTTPException(status_code=404, detail="No enrollment token found for this customer. Generate one first.")

    server_url = (body.server_url or await get_server_url(db)).rstrip("/")

    kwargs = dict(
        customer_id=str(customer.id),
        customer_name=customer.name,
        enrollment_token=token_row.token,
        server_url=server_url,
        arch=body.arch,
    )

    fmt = body.format.lower()

    # ── Build package ─────────────────────────────────────────────────────────
    try:
        if fmt == "zip":
            data      = build_zip(**kwargs)
            mime      = "application/zip"
            filename  = f"nocko-mdm-agent-{customer.slug}.zip"

        elif fmt == "exe":
            try:
                data     = build_exe(**kwargs)
                mime     = "application/octet-stream"
                filename = f"nocko-mdm-agent-{customer.slug}-setup.exe"
            except EXEMissing as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"EXE generation unavailable on this server: {e}. Install NSIS: apt install nsis"
                )

        elif fmt == "msi":
            try:
                data     = build_msi(**kwargs)
                mime     = "application/octet-stream"
                filename = f"nocko-mdm-agent-{customer.slug}.msi"
            except MSIMissing as e:
                raise HTTPException(
                    status_code=503,
                    detail=f"MSI generation unavailable on this server: {e}. Install msitools: apt install msitools"
                )

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
