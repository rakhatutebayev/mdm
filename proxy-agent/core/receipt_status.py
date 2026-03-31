"""
SNMP «приём данных» по снимкам poll_diag (общая логика для UI, API и HEALTH-лога).
"""
from __future__ import annotations

import time
from typing import Any

# Считаем приём «свежим», если последний pub был не старше этого интервала (сек).
RECEIPT_FRESH_SEC = 900  # 15 мин


def _safe_float(x: Any, default: float = 0.0) -> float:
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _snmp_error_hint(tier: dict[str, Any]) -> str:
    """Короткая подсказка из poll_diag.snmp_error_samples для UI."""
    samples = tier.get("snmp_error_samples")
    if not isinstance(samples, list) or not samples:
        return ""
    first = samples[0]
    if not isinstance(first, dict):
        return ""
    err = (first.get("error") or "").strip()
    key = (first.get("target_key") or "").strip()
    oid = (first.get("oid") or "").strip()
    if not err:
        return ""
    tail = err if len(err) <= 220 else err[:217] + "..."
    if key and oid:
        return f" Пример ({key}): {tail}"
    return f" Пример: {tail}"


def receipt_for_snap(snap: dict[str, Any] | None) -> dict[str, Any]:
    """
    Human-readable SNMP data receipt status for one device.
    Keys: state, label, detail, badge_class (for templates / JSON).
    """
    empty = {
        "state": "unknown",
        "label": "Нет опроса",
        "detail": "Поллер ещё не писал снимок или устройство не в цикле.",
        "badge_class": "badge-gray",
    }
    if not snap:
        return empty

    now = time.time()
    fast = snap.get("fast") or {}
    slow = snap.get("slow") or {}
    if not isinstance(fast, dict):
        fast = {}
    if not isinstance(slow, dict):
        slow = {}

    def _tier_pub(t: dict) -> int:
        return _safe_int(t.get("values_published"), 0)

    def _tier_ts(t: dict) -> float:
        return _safe_float(t.get("ts"), 0.0)

    for tier_name, t in (("fast", fast), ("slow", slow)):
        err = t.get("error")
        if err:
            msg = str(err)
            if msg == "no_profile":
                msg = "нет профиля у устройства"
            elif msg == "bad_json_mapping":
                msg = "битый output_mapping у профиля"
            return {
                "state": "error",
                "label": "Ошибка конфигурации",
                "detail": f"{tier_name}: {msg}",
                "badge_class": "badge-red",
            }

    last_ts = 0.0
    last_pub = 0
    for t in (fast, slow):
        p = _tier_pub(t)
        ts = _tier_ts(t)
        if p > 0 and ts > last_ts:
            last_ts = ts
            last_pub = p

    if last_ts > 0:
        age = int(now - last_ts)
        if age <= RECEIPT_FRESH_SEC:
            return {
                "state": "receiving",
                "label": "Принимает данные",
                "detail": f"SNMP: {last_pub} ключ(ей) в последнем опросе · {age}s назад",
                "badge_class": "badge-green",
            }
        return {
            "state": "stale",
            "label": "Данные устарели",
            "detail": f"Последний приём: {last_pub} ключ(ей), {age // 60} мин назад",
            "badge_class": "badge-yellow",
        }

    for name, t in (("fast", fast), ("slow", slow)):
        tt = _safe_int(t.get("tier_total"), 0)
        if tt <= 0:
            continue
        macro = _safe_int(t.get("macro_skipped"), 0)
        snmp_f = _safe_int(t.get("snmp_failed"), 0)
        if macro >= tt:
            return {
                "state": "lld",
                "label": "Только LLD в OID",
                "detail": f"{name}: все {tt} items с {{#…}} — SNMP GET не выполняется",
                "badge_class": "badge-red",
            }
        if snmp_f >= (tt - macro) and (tt - macro) > 0:
            hint = _snmp_error_hint(t)
            return {
                "state": "snmp",
                "label": "SNMP не отвечает",
                "detail": (
                    f"{name}: все GET провалились — проверьте community, IP, ACL, v3."
                    f"{hint or ' См. poll_diag / «SNMP debug» в консоли.'}"
                ),
                "badge_class": "badge-red",
            }

    inv = snap.get("inventory") or {}
    if isinstance(inv, dict) and _safe_int(inv.get("values_published"), 0) > 0:
        age = int(now - _safe_float(inv.get("ts"), 0.0))
        return {
            "state": "inventory_only",
            "label": "Только инвентарь",
            "detail": f"{inv.get('values_published')} ключ(ей) в inventory · {age}s назад (метрик fast/slow нет)",
            "badge_class": "badge-yellow",
        }

    return {
        "state": "idle",
        "label": "Метрик нет",
        "detail": "В последнем опросе 0 значений: дедуп, range, или нет скалярных items в профиле.",
        "badge_class": "badge-yellow",
    }
