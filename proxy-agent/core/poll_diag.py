"""
Last SNMP poll diagnostics per device (proxy-side troubleshooting).
Updated by snmp_poller; read by Local Console / logs.
"""
from __future__ import annotations

import time
from threading import Lock
from typing import Any

_lock = Lock()
# device_id -> { "fast": {...}, "slow": {...}, "inventory": {...} }
_by_device: dict[str, dict[str, Any]] = {}


def record_tier(device_id: str, tier: str, info: dict[str, Any]) -> None:
    """Merge one poll tier snapshot for a device."""
    # Apply info first so caller cannot overwrite agent-owned wall clock (bad ts breaks UI / receipt_status).
    snap = {
        **info,
        "ts": time.time(),
    }
    with _lock:
        d = _by_device.setdefault(device_id, {})
        d[tier] = snap


def get_snapshot(device_id: str) -> dict[str, Any]:
    with _lock:
        return dict(_by_device.get(device_id, {}))


def get_all_devices() -> dict[str, dict[str, Any]]:
    with _lock:
        return {k: dict(v) for k, v in _by_device.items()}


def clear_device(device_id: str) -> None:
    """Forget in-memory diagnostics for one device."""
    with _lock:
        _by_device.pop(device_id, None)


def oid_has_lld_macro(oid: str) -> bool:
    """Zabbix LLD placeholders cannot be used with plain SNMP GET."""
    return bool(oid) and "{#" in oid
