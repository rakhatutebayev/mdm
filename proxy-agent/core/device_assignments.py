"""
Apply server-managed device_assignments from GET /api/v1/agent/config (TZ §4.6).

When MDM returns a non-empty device_assignments list, we upsert matching rows
in local SQLite `devices` so the poller can run without manual /devices entry.
"""
from __future__ import annotations

import re
from typing import Any

from core.database import Device, DeviceProfile, get_session
from core.logger import log
from sqlmodel import select


def _norm_status(raw: Any) -> str:
    s = str(raw or "active").strip().lower()
    if s in ("active", "offline", "unsupported"):
        return s
    return "active"


def _norm_snmp_ver(raw: Any) -> str:
    return "3" if str(raw or "").strip() == "3" else "2c"


def apply_device_assignments_from_config(config: dict[str, Any]) -> tuple[int, list[str]]:
    """
    Upsert Device rows from config['device_assignments'].

    If the key is missing, returns (0, []) and leaves local DB unchanged.
    Each assignment expects at least device_uid; ip strongly recommended.

    Returns (upsert_count, log_lines for debugging/UI).
    """
    raw = config.get("device_assignments")
    if raw is None:
        return 0, []
    if not isinstance(raw, list):
        log.warning("device_assignments in server config is not a list — ignored")
        return 0, ["device_assignments: not a list"]

    lines: list[str] = []
    n = 0
    with get_session() as s:
        for row in raw:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("device_uid") or row.get("device_id") or "").strip()
            if not uid:
                lines.append("skip: missing device_uid")
                continue
            if not re.match(r"^[a-zA-Z0-9_.-]+$", uid):
                lines.append(f"skip {uid!r}: invalid uid chars")
                continue

            ip = str(row.get("ip") or "").strip()
            slug_in = str(row.get("profile_slug") or "").strip()
            resolved_profile: str | None = None
            if slug_in:
                if s.exec(
                    select(DeviceProfile).where(DeviceProfile.profile_id == slug_in)
                ).first():
                    resolved_profile = slug_in
                else:
                    lines.append(
                        f"{uid}: profile_slug {slug_in!r} not in local agent profiles — "
                        "import Zabbix template first; profile_id unchanged"
                    )

            ver = _norm_snmp_ver(row.get("snmp_version"))
            community = str(row.get("snmp_community") or "public").strip() or "public"
            v3_user = str(row.get("snmp_v3_user") or "").strip()
            v3_auth = str(row.get("snmp_v3_auth_key") or "").strip()
            v3_priv = str(row.get("snmp_v3_priv_key") or "").strip()
            st = _norm_status(row.get("status"))

            p_fast = row.get("poll_interval_fast")
            p_slow = row.get("poll_interval_slow")
            p_inv = row.get("poll_interval_inventory")
            try:
                interval_fast = int(p_fast) if p_fast is not None else 60
            except (TypeError, ValueError):
                interval_fast = 60
            try:
                interval_slow = int(p_slow) if p_slow is not None else 300
            except (TypeError, ValueError):
                interval_slow = 300
            try:
                interval_inv = int(p_inv) if p_inv is not None else 86400
            except (TypeError, ValueError):
                interval_inv = 86400

            existing = s.exec(select(Device).where(Device.device_id == uid)).first()
            if existing:
                if ip:
                    existing.ip = ip
                if resolved_profile is not None:
                    existing.profile_id = resolved_profile
                existing.snmp_version = ver
                existing.snmp_community = community
                existing.snmp_v3_user = v3_user
                existing.snmp_v3_auth_key = v3_auth
                existing.snmp_v3_priv_key = v3_priv
                existing.status = st
                existing.poll_interval_fast = max(1, interval_fast)
                existing.poll_interval_slow = max(1, interval_slow)
                existing.poll_interval_inventory = max(60, interval_inv)
                s.add(existing)
                lines.append(f"updated {uid}")
            else:
                if not ip:
                    lines.append(f"skip {uid}: no ip (cannot create new device)")
                    continue
                s.add(
                    Device(
                        device_id=uid,
                        ip=ip,
                        profile_id=resolved_profile,
                        snmp_version=ver,
                        snmp_community=community,
                        snmp_v3_user=v3_user,
                        snmp_v3_auth_key=v3_auth,
                        snmp_v3_priv_key=v3_priv,
                        status=st,
                        poll_interval_fast=max(1, interval_fast),
                        poll_interval_slow=max(1, interval_slow),
                        poll_interval_inventory=max(60, interval_inv),
                    )
                )
                lines.append(f"created {uid}")
            n += 1
        s.commit()

    if n:
        log.info(f"device_assignments applied: {n} device(s) upserted from server config")
    return n, lines
