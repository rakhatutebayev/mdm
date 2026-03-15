from __future__ import annotations

import os
import platform
import socket
import time
import uuid
from typing import Any

import psutil


def _safe(callable_obj, fallback: Any = "") -> Any:
    try:
        return callable_obj()
    except Exception:
        return fallback


def _first_ipv4() -> str:
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if entry.family == socket.AF_INET and not entry.address.startswith("127."):
                return entry.address
    return ""


def _first_mac() -> str:
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if getattr(psutil, "AF_LINK", object()) == entry.family and entry.address:
                return entry.address
    return ""


def collect_enrollment_payload(config) -> dict[str, Any]:
    return {
        "customer_id": config.customer_id,
        "enrollment_token": config.enrollment_token,
        "device_name": socket.gethostname(),
        "platform": "Windows" if os.name == "nt" else platform.system(),
        "device_type": "Desktop",
        "model": platform.machine(),
        "manufacturer": platform.node(),
        "serial_number": "",
        "udid": hex(uuid.getnode())[2:].upper(),
        "os_version": platform.platform(),
        "architecture": platform.machine(),
        "owner": os.getenv("USERNAME", ""),
        "enrollment_method": "WindowsService",
        "agent_version": config.agent_version,
        "network": {
            "ip_address": _first_ipv4(),
            "mac_address": _first_mac(),
            "hostname": socket.gethostname(),
            "wifi_ssid": "",
            "connection_type": "Ethernet",
            "dns_server": "",
            "default_gateway": "",
        },
        "monitors": [],
    }


def collect_checkin_payload(config) -> dict[str, Any]:
    vm = _safe(psutil.virtual_memory)
    disk = _safe(lambda: psutil.disk_usage("C:\\" if os.name == "nt" else "/"))
    boot_time = _safe(psutil.boot_time, 0.0)

    return {
        "device_id": config.device_id,
        "agent_version": config.agent_version,
        "os_version": platform.platform(),
        "ip_address": _first_ipv4(),
        "cpu_pct": _safe(lambda: round(psutil.cpu_percent(interval=1), 1), None),
        "ram_used_gb": _safe(lambda: round((vm.used / (1024 ** 3)), 2), None) if vm else None,
        "ram_total_gb": _safe(lambda: round((vm.total / (1024 ** 3)), 2), None) if vm else None,
        "disk_used_gb": _safe(lambda: round((disk.used / (1024 ** 3)), 2), None) if disk else None,
        "disk_total_gb": _safe(lambda: round((disk.total / (1024 ** 3)), 2), None) if disk else None,
        "uptime_seconds": _safe(lambda: max(0, int(time.time() - boot_time)), 0),
    }
