"""Dashboard stats router — aggregate data from DB."""
from __future__ import annotations

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from fastapi import APIRouter, Depends

from database import get_db
from models import Device, Customer

router = APIRouter(prefix="/api/v1/dashboard", tags=["dashboard"])


@router.get("/stats")
async def get_dashboard_stats(
    customer_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Return top-level MDM stats: device counts, platform breakdown, recent devices."""

    # ── Base query ─────────────────────────────────────────────────────────────
    base = select(Device)
    if customer_id:
        cust_result = await db.execute(
            select(Customer).where(
                (Customer.slug == customer_id) | (Customer.id == customer_id)
            )
        )
        cust = cust_result.scalar_one_or_none()
        if cust:
            base = base.where(Device.customer_id == cust.id)

    result = await db.execute(base)
    devices = result.scalars().all()

    total = len(devices)
    compliant = sum(1 for d in devices if d.status == "Compliant")
    non_compliant = sum(1 for d in devices if d.status == "Non-Compliant")
    pending = sum(1 for d in devices if d.status in ("Pending", "Pending Enrollment"))

    # ── Platform breakdown ─────────────────────────────────────────────────────
    platform_counts: dict[str, int] = {}
    for d in devices:
        p = (d.platform or "Unknown")
        platform_counts[p] = platform_counts.get(p, 0) + 1

    platforms = [
        {"name": p, "count": c, "pct": round(c / total * 100) if total else 0}
        for p, c in sorted(platform_counts.items(), key=lambda x: -x[1])
    ]

    # ── Recent 5 devices (by last_checkin desc) ──────────────────────────────
    recent_q = select(Device).order_by(Device.last_checkin.desc().nullslast()).limit(5)
    if customer_id and cust:
        recent_q = recent_q.where(Device.customer_id == cust.id)
    recent_result = await db.execute(recent_q)
    recent = recent_result.scalars().all()

    def fmt_time(dt):
        if not dt:
            return "Never"
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        diff = now - dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else now - dt
        seconds = int(diff.total_seconds())
        if seconds < 60:
            return "Just now"
        if seconds < 3600:
            return f"{seconds // 60} min ago"
        if seconds < 86400:
            return f"{seconds // 3600} hour{'s' if seconds // 3600 > 1 else ''} ago"
        return f"{seconds // 86400} day{'s' if seconds // 86400 > 1 else ''} ago"

    recent_devices = [
        {
            "id": str(d.id),
            "name": d.device_name or d.model or "Unknown Device",
            "user": d.owner or "—",
            "platform": d.platform or "Unknown",
            "status": d.status or "Unknown",
            "last_seen": fmt_time(d.last_checkin),
        }
        for d in recent
    ]

    return {
        "total": total,
        "compliant": compliant,
        "non_compliant": non_compliant,
        "pending": pending,
        "platforms": platforms,
        "recent_devices": recent_devices,
    }
