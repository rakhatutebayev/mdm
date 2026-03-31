"""
Стабильные пути консоли для отладки (latest.json, snmp-debug.json).
Вынесено в core, чтобы и HTML, и diagnostics.json использовали одну логику.
"""
from __future__ import annotations

import re
from typing import Any

_DEVICE_ID_PATH = re.compile(r"^[a-zA-Z0-9_.-]+$")


def device_id_path_ok(s: str) -> bool:
    return bool(_DEVICE_ID_PATH.match(s or ""))


def device_debug_urls(device_id: str) -> dict[str, Any]:
    """Относительные URL для устройства; None если UID небезопасен для пути."""
    did = (device_id or "").strip()
    if not device_id_path_ok(did):
        return {
            "latest_json": None,
            "snmp_debug_json": None,
            "path_ok": False,
        }
    return {
        "latest_json": f"/devices/{did}/latest.json",
        "snmp_debug_json": f"/devices/{did}/snmp-debug.json",
        "path_ok": True,
    }
