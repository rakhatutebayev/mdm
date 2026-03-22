"""
Offline queue manager for NOCKO Proxy Agent.

Implements FIFO replay with TTL enforcement and downsampling for large backlogs.
Rules from proxy_agent_tz.md Section 4.5 (Replay Semantics).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from core.database import QueueItem, get_session
from core.logger import log
from sqlmodel import select

# TTL constants (seconds)
_METRICS_TTL = 86400          # 24h — stale metrics are dropped
_EVENTS_TTL = 604800          # 7d  — events are kept longer (FIFO, no drop)
_MAX_METRICS_BACKLOG = 5000   # beyond this threshold, downsample to 1-in-3


from typing import Optional


def enqueue(payload_type: str, payload: dict, device_id: Optional[str] = None) -> int:
    """
    Add a record to the outbound queue.
    Returns the queue item id.
    """
    now_unix = int(time.time())
    item = QueueItem(
        type=payload_type,
        device_id=device_id,
        payload=json.dumps(payload),
        status="pending",
        enqueue_timestamp=now_unix,
    )
    with get_session() as session:
        session.add(item)
        session.commit()
        session.refresh(item)
        return item.id


def get_pending(limit: int = 100) -> list[QueueItem]:
    """Fetch oldest pending items (FIFO), respecting TTL and backlog rules."""
    with get_session() as session:
        items = session.exec(
            select(QueueItem)
            .where(QueueItem.status == "pending")
            .order_by(QueueItem.id)
            .limit(limit * 3)   # over-fetch to allow filtering
        ).all()

    now = int(time.time())
    _METRIC_TYPES = {"metrics", "metrics.fast", "metrics.slow"}
    metrics_items = [i for i in items if i.type in _METRIC_TYPES]
    other_items = [i for i in items if i.type not in _METRIC_TYPES]

    # Drop expired metrics
    fresh_metrics = [i for i in metrics_items if (now - i.enqueue_timestamp) < _METRICS_TTL]

    # Downsample if large backlog
    if len(fresh_metrics) > _MAX_METRICS_BACKLOG:
        log.warning(f"Metrics backlog {len(fresh_metrics)} > {_MAX_METRICS_BACKLOG}, downsampling 1-in-3")
        fresh_metrics = fresh_metrics[::3]

    combined = (fresh_metrics + other_items)[:limit]
    return combined


def mark_sent(item_id: int) -> None:
    """Mark a queue item as successfully sent."""
    with get_session() as session:
        item = session.get(QueueItem, item_id)
        if item:
            item.status = "sent"
            item.updated_at = datetime.utcnow()
            session.commit()


def mark_failed(item_id: int) -> None:
    """Increment attempt count; mark failed if too many retries."""
    with get_session() as session:
        item = session.get(QueueItem, item_id)
        if item:
            item.attempts += 1
            item.updated_at = datetime.utcnow()
            if item.attempts >= 5:
                item.status = "failed"
                log.warning(f"Queue item {item_id} marked failed after 5 attempts")
            session.commit()


def prune_sent(older_than_hours: int = 48) -> int:
    """Delete sent items older than threshold. Returns count deleted."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(hours=older_than_hours)
    with get_session() as session:
        items = session.exec(
            select(QueueItem)
            .where(QueueItem.status == "sent")
            .where(QueueItem.updated_at < cutoff)
        ).all()
        count = len(items)
        for item in items:
            session.delete(item)
        session.commit()
    if count:
        log.info(f"Pruned {count} sent queue items")
    return count


def queue_size(status: str = "pending") -> int:
    """Count items by status."""
    with get_session() as session:
        return len(session.exec(select(QueueItem).where(QueueItem.status == status)).all())
