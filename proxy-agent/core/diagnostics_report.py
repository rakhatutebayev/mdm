"""
Сводка самодиагностики агента: JSON для API и одна строка для лога (без действий оператора).
"""
from __future__ import annotations

import os
import time
from collections import Counter
from typing import Any
from urllib.parse import urlparse

from sqlmodel import select

from core import poll_diag
from core import queue as q
from core.config import config
from core.database import Device, get_session, kv_get
from core.mqtt_client import mqtt_client
from core.receipt_status import receipt_for_snap
from core.debug_urls import device_debug_urls


def _broker_hostname(broker_url: str) -> str:
    if not (broker_url or "").strip():
        return "—"
    h = urlparse(broker_url.strip()).hostname
    return h or "—"


def build_diagnostics_report() -> dict[str, Any]:
    """Полный снимок для GET /api/v1/diagnostics.json и внутренних проверок."""
    snaps = poll_diag.get_all_devices()
    broker = (kv_get("broker_url", "") or config.server.broker_url or "").strip()

    devices_out: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()

    with get_session() as s:
        devs = list(s.exec(select(Device)).all())

    for d in devs:
        rec = receipt_for_snap(snaps.get(d.device_id))
        st = str(rec.get("state") or "unknown")
        state_counts[st] += 1
        devices_out.append(
            {
                "device_id": d.device_id,
                "ip": d.ip,
                "profile_id": d.profile_id or "",
                "receipt": {
                    "state": rec.get("state"),
                    "label": rec.get("label"),
                    "detail": rec.get("detail"),
                },
                "debug_urls": device_debug_urls(d.device_id),
            }
        )

    problems_n = (
        state_counts.get("error", 0)
        + state_counts.get("lld", 0)
        + state_counts.get("snmp", 0)
    )

    registered = kv_get("registered", "false") == "true"

    return {
        "schema": "nocko_agent_diagnostics/1",
        "ts": int(time.time()),
        "agent": {
            "tenant_id": str(config.server.tenant_id or kv_get("tenant_id", "") or ""),
            "agent_id": str(config.server.agent_id or kv_get("agent_id", "") or ""),
            "registered": registered,
        },
        "mqtt": {
            "connected": mqtt_client.connected,
            "queue_pending": q.queue_size("pending"),
            "broker_url": broker,
            "broker_host": _broker_hostname(broker),
        },
        "devices_total": len(devs),
        "summary": {
            "receiving": state_counts.get("receiving", 0),
            "stale": state_counts.get("stale", 0),
            "inventory_only": state_counts.get("inventory_only", 0),
            "idle_unknown": state_counts.get("idle", 0) + state_counts.get("unknown", 0),
            "problems": problems_n,
            "by_state": dict(state_counts),
        },
        "devices": devices_out,
    }


def health_log_line() -> str:
    """
    Одна строка INFO для tail лога (каждые N минут из main).
    Формат стабилен для grep: префикс HEALTH_SUMMARY
    """
    r = build_diagnostics_report()
    mq = r["mqtt"]
    sm = r["summary"]
    reg = "yes" if r["agent"]["registered"] else "no"
    mqtt_s = "yes" if mq["connected"] else "no"
    return (
        "HEALTH_SUMMARY "
        f"mqtt={mqtt_s} queue={mq['queue_pending']} "
        f"reg={reg} dev={r['devices_total']} "
        f"recv={sm['receiving']} stale={sm['stale']} inv_only={sm['inventory_only']} "
        f"idle_unk={sm['idle_unknown']} prob={sm['problems']} "
        f"broker={mq['broker_host']}"
    )


def health_log_interval_sec() -> int:
    """Интервал HEALTH-лога; 0 = отключить (NOCKO_HEALTH_LOG_SEC=0)."""
    raw = (os.environ.get("NOCKO_HEALTH_LOG_SEC") or "").strip()
    if raw == "0":
        return 0
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return 300  # 5 мин по умолчанию
