"""
Trends Aggregator — Background Worker
Rolls up history_* data into trends_uint and trends_float (hourly buckets).
Runs as an asyncio periodic task on the portal backend.

Per portal_backend_tz.md Section 2.10:
  trends_* = per-hour (min, max, avg, count) aggregation of history_*.
  UPSERT on (tenant_id, device_id, item_id, hour).
  Runs every hour. Processes data from the previous completed hour.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from agent_models import HistoryUint, HistoryFloat, TrendUint, TrendFloat

log = logging.getLogger("nocko.trends")

# Run interval: every 5 minutes checking for a completed hour to aggregate
_CHECK_INTERVAL = 300      # seconds between main loop iterations
_BUCKET_SIZE = 3600        # 1 hour in seconds
_LOOKBACK_HOURS = 3        # how many past hours to recompute (handles late arrivals)


class TrendsAggregator:
    """
    Hourly rollup worker.
    - Computes (min, max, avg, count) per (tenant_id, device_id, item_id, hour)
    - Upserts into trends_uint and trends_float
    - Processes both history tables independently
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory
        self._running = False

    async def run_forever(self) -> None:
        """Main loop — runs until stopped."""
        self._running = True
        log.info("Trends aggregator started")
        while self._running:
            try:
                await self._aggregate_recent()
            except Exception as e:
                log.error(f"Trends aggregation error: {e}", exc_info=True)
            await asyncio.sleep(_CHECK_INTERVAL)

    def stop(self) -> None:
        self._running = False

    async def _aggregate_recent(self) -> None:
        """Aggregate the last N completed hours."""
        now = int(time.time())
        # Process last _LOOKBACK_HOURS completed hour buckets
        for offset in range(1, _LOOKBACK_HOURS + 1):
            hour_ts = ((now // _BUCKET_SIZE) - offset) * _BUCKET_SIZE
            async with self._sf() as session:
                await self._aggregate_hour_uint(hour_ts, session)
                await self._aggregate_hour_float(hour_ts, session)
                await session.commit()

    async def _aggregate_hour_uint(self, hour_ts: int, db: AsyncSession) -> None:
        """Rollup history_uint for a specific hour bucket."""
        end_ts = hour_ts + _BUCKET_SIZE

        # Group by (tenant_id, device_id, item_id) for this hour
        result = await db.execute(
            select(
                HistoryUint.tenant_id,
                HistoryUint.device_id,
                HistoryUint.item_id,
                func.min(HistoryUint.value).label("min_val"),
                func.max(HistoryUint.value).label("max_val"),
                func.avg(HistoryUint.value).label("avg_val"),
                func.count(HistoryUint.id).label("cnt"),
            ).where(
                HistoryUint.clock >= hour_ts,
                HistoryUint.clock < end_ts,
            ).group_by(
                HistoryUint.tenant_id,
                HistoryUint.device_id,
                HistoryUint.item_id,
            )
        )
        rows = result.all()
        if not rows:
            return

        for row in rows:
            await _upsert_trend(db, TrendUint, {
                "tenant_id": row.tenant_id,
                "device_id": row.device_id,
                "item_id": row.item_id,
                "hour": hour_ts,
                "min": int(row.min_val),
                "max": int(row.max_val),
                "avg": float(row.avg_val),
                "count": int(row.cnt),
            })

        log.debug(f"Aggregated {len(rows)} uint items for hour {hour_ts}")

    async def _aggregate_hour_float(self, hour_ts: int, db: AsyncSession) -> None:
        """Rollup history_float for a specific hour bucket."""
        end_ts = hour_ts + _BUCKET_SIZE

        result = await db.execute(
            select(
                HistoryFloat.tenant_id,
                HistoryFloat.device_id,
                HistoryFloat.item_id,
                func.min(HistoryFloat.value).label("min_val"),
                func.max(HistoryFloat.value).label("max_val"),
                func.avg(HistoryFloat.value).label("avg_val"),
                func.count(HistoryFloat.id).label("cnt"),
            ).where(
                HistoryFloat.clock >= hour_ts,
                HistoryFloat.clock < end_ts,
            ).group_by(
                HistoryFloat.tenant_id,
                HistoryFloat.device_id,
                HistoryFloat.item_id,
            )
        )
        rows = result.all()
        if not rows:
            return

        for row in rows:
            await _upsert_trend(db, TrendFloat, {
                "tenant_id": row.tenant_id,
                "device_id": row.device_id,
                "item_id": row.item_id,
                "hour": hour_ts,
                "min": float(row.min_val),
                "max": float(row.max_val),
                "avg": float(row.avg_val),
                "count": int(row.cnt),
            })

        log.debug(f"Aggregated {len(rows)} float items for hour {hour_ts}")


async def _upsert_trend(db: AsyncSession, model_cls: Any, data: dict) -> None:
    """
    Upsert into trends_* table.
    Uses SQLAlchemy merge (PK-based) for portability.
    PostgreSQL: replaces with ON CONFLICT DO UPDATE.
    """
    existing = await db.get(
        model_cls,
        (data["tenant_id"], data["device_id"], data["item_id"], data["hour"])
    )
    if existing:
        existing.min = data["min"]
        existing.max = data["max"]
        existing.avg = data["avg"]
        existing.count = data["count"]
    else:
        db.add(model_cls(**data))


# ── Singleton and lifecycle ────────────────────────────────────────────────────
_aggregator: TrendsAggregator | None = None


def get_aggregator(session_factory: async_sessionmaker) -> TrendsAggregator:
    global _aggregator
    if _aggregator is None:
        _aggregator = TrendsAggregator(session_factory)
    return _aggregator
