"""
Device profile readiness for Local Console (TZ §2.4 — profile requisites + operational status).
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from core.database import Device, DeviceProfile


def _oid_is_literal_gettable(oid: str) -> bool:
    """LLD macros like {#SNMPINDEX} are not valid for a plain SNMP GET probe."""
    return bool(oid) and "{#" not in oid


def pick_probe_oid(mapping: list[dict[str, Any]]) -> str | None:
    """First literal OID suitable for SNMP GET (skip LLD macro placeholders)."""
    for tier in ("fast", "slow", "inventory"):
        for item in mapping:
            if not isinstance(item, dict):
                continue
            if item.get("poll_class") == tier:
                oid = (item.get("source_oid") or "").strip()
                if _oid_is_literal_gettable(oid):
                    return oid
    for item in mapping:
        if not isinstance(item, dict):
            continue
        oid = (item.get("source_oid") or "").strip()
        if _oid_is_literal_gettable(oid):
            return oid
    return None


@dataclass
class ProfileListRow:
    profile_id: str
    profile_name: str
    profile_vendor: str
    profile_version: str
    items_count: int
    devices_count: int
    devices_recent: int  # last_seen within freshness_sec
    status_key: str  # not_ready | ready_unused | active | verified_ok | verify_failed
    status_label: str
    verify_at: int | None
    verify_ok: bool | None
    verify_message: str


def _parse_mapping(raw: str) -> list[dict[str, Any]]:
    try:
        m = json.loads(raw or "[]")
        return m if isinstance(m, list) else []
    except Exception:
        return []


def build_profile_row(
    session: Session,
    profile: DeviceProfile,
    verify_blob: dict[str, Any] | None,
    *,
    freshness_sec: int = 900,
) -> ProfileListRow:
    """Compute TZ-aligned readiness row for one profile."""
    now = int(time.time())
    mapping = _parse_mapping(profile.output_mapping)
    n_items = len(mapping)

    devs = session.exec(
        select(Device).where(Device.profile_id == profile.profile_id)
    ).all()
    n_dev = len(devs)
    n_recent = sum(1 for d in devs if d.last_seen and (now - d.last_seen) <= freshness_sec)

    v_at = int(verify_blob["at"]) if verify_blob and "at" in verify_blob else None
    v_ok = verify_blob.get("ok") if verify_blob else None
    v_msg = str(verify_blob.get("message", "")) if verify_blob else ""

    verify_fresh = v_at and (now - v_at) < 86400

    if n_items == 0:
        key, label = "not_ready", "Not ready — empty or invalid mapping"
    elif n_dev == 0:
        key, label = "ready_unused", "Ready — mapping OK, assign devices to go live"
    elif verify_fresh and v_ok is True:
        key, label = "verified_ok", "SNMP check OK (manual verify)"
    elif verify_fresh and v_ok is False:
        key, label = "verify_failed", "SNMP check failed — see profile detail"
    elif n_recent > 0:
        key, label = "active", "In use — recent poll activity"
    else:
        key, label = "active", "In use — run Verify or wait for poller"

    return ProfileListRow(
        profile_id=profile.profile_id,
        profile_name=profile.profile_name or "—",
        profile_vendor=profile.profile_vendor or "—",
        profile_version=profile.profile_version or "—",
        items_count=n_items,
        devices_count=n_dev,
        devices_recent=n_recent,
        status_key=key,
        status_label=label,
        verify_at=v_at,
        verify_ok=v_ok,
        verify_message=v_msg,
    )
