"""
SNMP Poller for NOCKO Proxy Agent.

3-phase polling per device per poll_class:
  Phase 1 — Walk:      SNMP BULKWALK for walk[] master items → stored in _walk_cache
  Phase 2 — GET:       scalar SNMP GET for direct OID items (legacy + new get[] format)
  Phase 3 — Dependent: extract values from _walk_cache per SNMP_WALK_VALUE logic, incl. LLD instances

Supports: SNMPv2c and SNMPv3 (authPriv).
Library: puresnmp (pure-Python, no net-snmp dependency).
TZ Reference: proxy_agent_tz.md §8
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from typing import Any

import puresnmp

from core.config import config
from core.database import Device, DeviceProfile, InventoryCache, get_session
from core.logger import log
from core.mqtt_client import mqtt_client
from core import poll_diag
from sqlmodel import Session, select


def _get_profile_by_slug(session: Session, profile_id: str | None) -> DeviceProfile | None:
    """Load DeviceProfile by string profile_id (slug), not SQLModel PK."""
    if not profile_id:
        return None
    return session.exec(
        select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
    ).first()


# ──────────────────────────────────────────────────────────────────────────────
# Value cache — for Discard unchanged + metric_keepalive
# ──────────────────────────────────────────────────────────────────────────────
_last_values: dict[str, dict[str, Any]] = {}   # {device_id: {key: value}}
_last_sent: dict[str, dict[str, float]] = {}   # {device_id: {key: timestamp}}
_KEEPALIVE_INTERVAL = 300  # seconds — send unchanged value every 5 min

# Walk result cache: {device_id: {master_key: {normalized_oid: value}}}
_walk_cache: dict[str, dict[str, dict[str, Any]]] = {}

# Remote command / control plane (mutable from main thread — poller loop reads each tick)
_polling_paused: bool = False
_immediate_inventory: bool = False
_immediate_metrics_fast: bool = False
_immediate_metrics_slow: bool = False


def pause_polling() -> None:
    global _polling_paused
    _polling_paused = True
    log.info("SNMP polling paused")


def resume_polling() -> None:
    global _polling_paused
    _polling_paused = False
    log.info("SNMP polling resumed")


def request_immediate_inventory() -> None:
    global _immediate_inventory
    _immediate_inventory = True


def request_immediate_metrics(include_fast: bool = True, include_slow: bool = True) -> None:
    global _immediate_metrics_fast, _immediate_metrics_slow
    if include_fast:
        _immediate_metrics_fast = True
    if include_slow:
        _immediate_metrics_slow = True


def _should_send(device_id: str, key: str, value: Any) -> bool:
    """Return True if value changed or keepalive interval elapsed."""
    prev = _last_values.get(device_id, {}).get(key)
    last_ts = _last_sent.get(device_id, {}).get(key, 0)

    changed = (prev != value)
    keepalive_due = (time.time() - last_ts) >= _KEEPALIVE_INTERVAL

    return changed or keepalive_due


def _record_sent(device_id: str, key: str, value: Any) -> None:
    _last_values.setdefault(device_id, {})[key] = value
    _last_sent.setdefault(device_id, {})[key] = time.time()


def forget_device(device_id: str) -> None:
    """Drop in-memory dedup/keepalive and walk-cache state for a removed device."""
    _last_values.pop(device_id, None)
    _last_sent.pop(device_id, None)
    _walk_cache.pop(device_id, None)


def _preview_keys(data: dict[str, Any], limit: int = 12) -> list[str]:
    """Subset of target_key names for diagnostics."""
    keys = sorted(data.keys(), key=str)
    return keys[:limit]


_MAX_SNMP_ERR_LEN = 420
_MAX_ERROR_SAMPLES = 8


def _format_snmp_exc(exc: Exception) -> str:
    msg = str(exc).strip() or repr(exc)
    raw = f"{type(exc).__name__}: {msg}"
    return raw if len(raw) <= _MAX_SNMP_ERR_LEN else raw[: _MAX_SNMP_ERR_LEN - 3] + "..."


def _preview_snmp_value(val: Any, limit: int = 160) -> str | None:
    if val is None:
        return None
    s = repr(val)
    return s if len(s) <= limit else s[: limit - 3] + "..."


# ──────────────────────────────────────────────────────────────────────────────
# OID normalization
# ──────────────────────────────────────────────────────────────────────────────
def _normalize_oid(oid: Any) -> str:
    """Strip leading dot, convert to consistent string form."""
    return str(oid).strip().lstrip(".")


def _sanitize_metric_key(raw: str) -> str:
    """Quick sanitizer for dynamically built LLD keys."""
    key = re.sub(r"\{[^{}]+\}", "", raw)
    key = re.sub(r"[^a-zA-Z0-9._-]", ".", key)
    key = re.sub(r"\.{2,}", ".", key).strip(".")
    return key or "item"


# ──────────────────────────────────────────────────────────────────────────────
# SNMP helpers
# ──────────────────────────────────────────────────────────────────────────────
async def snmp_probe_oid(device: Device, oid: str) -> tuple[bool, str]:
    """
    One-shot SNMP GET for UI verification.
    Returns (success, short message for operator).
    """
    val, err = await _snmp_get(device.ip, oid, device)
    if val is None:
        detail = err or "unknown error (no exception text)"
        return False, f"No SNMP response from {device.ip} for OID {oid} — {detail}"
    return True, f"OK from {device.ip}: {val!r}"


def _snmp_client(device: Device) -> puresnmp.Client:
    """Build a puresnmp 2.x client for v2c/v3 devices."""
    if device.snmp_version == "3":
        auth = None
        priv = None
        if device.snmp_v3_auth_key:
            auth = puresnmp.Auth(device.snmp_v3_auth_key.encode(), "sha")
        if device.snmp_v3_priv_key:
            priv = puresnmp.Priv(device.snmp_v3_priv_key.encode(), "aes")
        creds = puresnmp.V3(device.snmp_v3_user, auth=auth, priv=priv)
    else:
        creds = puresnmp.V2C(device.snmp_community)
    return puresnmp.Client(device.ip, creds)


def _oid_arg(oid: str):
    """Use x690 ObjectIdentifier when available, otherwise pass raw string."""
    try:
        from x690.types import ObjectIdentifier
        return ObjectIdentifier(oid)
    except Exception:
        return oid


async def _snmp_get(ip: str, oid: str, device: Device) -> tuple[Any | None, str | None]:
    """Single SNMP GET. Returns (value, None) or (None, error_text)."""
    try:
        client = _snmp_client(device)
        result = await client.get(_oid_arg(oid))
        return result, None
    except Exception as e:
        err = _format_snmp_exc(e)
        log.debug(f"SNMP GET {ip} {oid}: {err}")
        return None, err


async def _snmp_walk(ip: str, base_oid: str, device: Device) -> dict[str, Any]:
    """SNMP WALK single tree. Returns {normalized_oid: value} dict."""
    try:
        client = _snmp_client(device)
        out: dict[str, Any] = {}
        async for row in client.bulkwalk([_oid_arg(base_oid)]):
            out[_normalize_oid(row.oid)] = row.value
        return out
    except Exception as e:
        log.debug(f"SNMP WALK {ip} {base_oid}: {e}")
        return {}


async def _snmp_bulkwalk_oids(device: Device, oid_list: list[str]) -> dict[str, Any]:
    """
    SNMP BULKWALK multiple OID trees in a single call.
    Returns {normalized_oid: value} dict for all subtrees combined.
    """
    if not oid_list:
        return {}
    try:
        client = _snmp_client(device)
        oid_args = [_oid_arg(o) for o in oid_list]
        out: dict[str, Any] = {}
        async for row in client.bulkwalk(oid_args):
            out[_normalize_oid(row.oid)] = row.value
        return out
    except Exception as e:
        log.debug(f"SNMP BULKWALK {device.ip} {oid_list[:2]}…: {e}")
        return {}


async def snmp_debug_report(device: Device) -> dict[str, Any]:
    """
    Step-by-step SNMP diagnostics for a device.
    Used by console (/devices/.../snmp-debug.json).
    """
    from core.profile_readiness import pick_probe_oid

    steps: list[dict[str, Any]] = []
    hints: list[str] = []

    async def _append_step(label: str, oid: str) -> bool:
        v, e = await _snmp_get(device.ip, oid, device)
        steps.append(
            {
                "step": label,
                "oid": oid,
                "ok": v is not None,
                "value_preview": _preview_snmp_value(v),
                "error": e,
            }
        )
        return v is not None

    mib2_ok = await _append_step("mib2_sysDescr", "1.3.6.1.2.1.1.1.0")
    await _append_step("mib2_sysUpTime", "1.3.6.1.2.1.1.3.0")

    probe_oid: str | None = None
    with get_session() as s:
        profile = _get_profile_by_slug(s, device.profile_id)
        if profile and profile.output_mapping:
            try:
                mapping = json.loads(profile.output_mapping)
                if isinstance(mapping, list):
                    probe_oid = pick_probe_oid(mapping)
            except Exception:
                pass

    probe_ok: bool | None = None
    if probe_oid:
        v, e = await _snmp_get(device.ip, probe_oid, device)
        probe_ok = v is not None
        steps.append(
            {
                "step": "profile_probe_oid",
                "oid": probe_oid,
                "ok": probe_ok,
                "value_preview": _preview_snmp_value(v),
                "error": e,
            }
        )
    else:
        steps.append(
            {
                "step": "profile_probe_oid",
                "oid": "",
                "ok": None,
                "value_preview": None,
                "error": None,
                "skipped": "no profile or no literal probe OID in output_mapping",
            }
        )

    if not mib2_ok:
        hints.append(
            "MIB-II (sysDescr) no response: check management IP (often separate iDRAC), "
            "SNMP enabled, community/SNMPv3 credentials, UDP/161 from agent host, and ACL on device."
        )
        err0 = ""
        for srow in steps:
            if srow.get("step") == "mib2_sysDescr":
                err0 = (srow.get("error") or "").lower()
                break
        if "timeout" in err0 or "timed out" in err0:
            hints.append("Timeout in error — network, firewall, or wrong IP.")
        if any(x in err0 for x in ("authentication", "authorization", "wrong digest", "cipher", "unknown user")):
            hints.append("Looks like SNMPv3/community auth error: wrong user, password or algorithm.")
    elif probe_oid and probe_ok is False:
        hints.append(
            "MIB-II OK but profile probe OID is unreachable: "
            "wrong firmware MIB, no object at that index, or enterprise OID restriction."
        )
    elif mib2_ok and probe_ok is True:
        hints.append(
            "Basic SNMP and profile probe OID OK. If UI still shows 'all GETs failed', "
            "check poll_diag.snmp_error_samples for specific keys and OIDs."
        )

    # Add walk cache info
    device_cache = _walk_cache.get(device.device_id, {})
    walk_cache_summary = {k: len(v) for k, v in device_cache.items()}

    return {
        "schema": "nocko_snmp_debug/2",
        "device_id": device.device_id,
        "ip": device.ip,
        "snmp_version": device.snmp_version,
        "steps": steps,
        "hints": hints,
        "walk_cache_masters": walk_cache_summary,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Walk cache helpers
# ──────────────────────────────────────────────────────────────────────────────
def _resolve_dependent_value(
    walk_result: dict[str, Any],
    base_oid: str,
    snmpindex: str,
    mode: str = "0",
) -> Any:
    """
    Extract a single value from walk_result at base_oid.snmpindex.
    walk_result keys are normalized OIDs (no leading dot).
    Returns None if not found.
    """
    bare_base = _normalize_oid(base_oid)
    target = f"{bare_base}.{snmpindex}"
    # Direct lookup
    val = walk_result.get(target)
    if val is not None:
        return val
    # Also try with leading dot stripped from stored key
    for k, v in walk_result.items():
        nk = _normalize_oid(k)
        if nk == target:
            return v
    return None


def _get_snmpindex_set(walk_result: dict[str, Any], base_oid: str) -> list[str]:
    """
    Return all single-level instance indexes found under base_oid in walk_result.
    E.g. for base=1.3.6.1.4.1.674...12.1.5 and results having keys:
      1.3.6.1.4.1.674...12.1.5.1 → index "1"
      1.3.6.1.4.1.674...12.1.5.2 → index "2"
    Returns ["1", "2"].
    """
    bare = _normalize_oid(base_oid)
    prefix = bare + "."
    indexes: set[str] = set()
    for oid_key in walk_result:
        nk = _normalize_oid(oid_key)
        if nk.startswith(prefix):
            suffix = nk[len(prefix):]
            # Only single-level index (no further dots)
            if suffix and "." not in suffix:
                indexes.add(suffix)
    return sorted(indexes, key=lambda x: int(x) if x.isdigit() else x)


# ──────────────────────────────────────────────────────────────────────────────
# Payload builder (TZ Section 7 envelope format)
# ──────────────────────────────────────────────────────────────────────────────
def _build_envelope(
    payload_type: str,
    device: Device,
    data: dict,
    clock: int,
    *,
    extras: dict[str, Any] | None = None,
) -> dict:
    env: dict[str, Any] = {
        "schema_version": "1.0",
        "tenant_id": config.server.tenant_id or "",
        "agent_id": config.server.agent_id or "",
        "sent_at": int(time.time()),
        "payload_type": payload_type,
        "records": [{
            "device_uid": device.device_id,
            "clock": clock,
            "enqueue_ts": int(time.time()),
            "data": data,
        }],
    }
    if extras:
        env.update(extras)
    return env


# ──────────────────────────────────────────────────────────────────────────────
# Single device poll — 3-phase
# ──────────────────────────────────────────────────────────────────────────────
async def poll_device(device: Device, poll_class: str) -> None:
    """Poll a single device for the given poll_class (fast / slow / inventory)."""
    did = device.device_id
    with get_session() as s:
        profile = _get_profile_by_slug(s, device.profile_id)
    if not profile:
        log.warning(f"Device {did} has no profile, skipping poll")
        poll_diag.record_tier(
            did,
            poll_class,
            {
                "profile_id": device.profile_id or "",
                "error": "no_profile",
                "tier_total": 0,
            },
        )
        return

    try:
        full_mapping = json.loads(profile.output_mapping)
    except Exception:
        log.error(f"Invalid output_mapping for profile {device.profile_id}")
        poll_diag.record_tier(
            did, poll_class, {"error": "bad_json_mapping", "tier_total": 0}
        )
        return

    # Filter to current poll_class
    mapping = [m for m in full_mapping if m.get("poll_class") == poll_class]

    # Split by snmp_type (default "get" for backward compat with old profiles)
    walk_items = [m for m in mapping if m.get("snmp_type") == "walk"]
    get_items = [m for m in mapping if m.get("snmp_type", "get") == "get"]
    dep_items = [m for m in mapping if m.get("snmp_type") == "dependent"]

    clock = int(time.time())
    data: dict[str, Any] = {}
    tier_total = len(walk_items) + len(get_items) + len(dep_items)
    macro_skip = 0
    walk_fail = 0
    snmp_fail = 0
    range_skip = 0
    dedup_skip = 0
    error_samples: list[dict[str, str]] = []

    device_walk_cache = _walk_cache.setdefault(did, {})

    # ── Phase 1: SNMP WALK (master items) ────────────────────────────────────
    for item in walk_items:
        walk_oids = item.get("walk_oids") or []
        master_key = item.get("target_key", "")
        if not walk_oids or not master_key:
            continue
        walk_result = await _snmp_bulkwalk_oids(device, walk_oids)
        if walk_result:
            device_walk_cache[master_key] = walk_result
            log.debug(
                f"[walk] {did}/{master_key}: cached {len(walk_result)} OID entries "
                f"from {len(walk_oids)} walk tree(s)"
            )
        else:
            walk_fail += 1
            if len(error_samples) < _MAX_ERROR_SAMPLES:
                error_samples.append({
                    "target_key": master_key,
                    "oid": str(walk_oids[:2]),
                    "error": "bulkwalk returned empty",
                })

    # ── Phase 2: Scalar SNMP GET ──────────────────────────────────────────────
    for item in get_items:
        oid = item.get("source_oid", "")
        key = item.get("target_key", "")
        if not oid or not key:
            continue
        if poll_diag.oid_has_lld_macro(oid):
            macro_skip += 1
            continue

        raw, gerr = await _snmp_get(device.ip, oid, device)
        if raw is None:
            snmp_fail += 1
            if len(error_samples) < _MAX_ERROR_SAMPLES:
                error_samples.append(
                    {"target_key": key, "oid": oid, "error": gerr or "unknown"}
                )
            continue

        scale = item.get("scale_multiplier", 1)
        try:
            value = float(raw) * scale if scale != 1 else raw
        except (TypeError, ValueError):
            value = raw

        vrange = item.get("valid_range")
        if vrange and isinstance(value, (int, float)):
            lo, hi = vrange.get("min", float("-inf")), vrange.get("max", float("inf"))
            if not (lo <= value <= hi):
                range_skip += 1
                continue

        if _should_send(did, key, value):
            data[key] = value
            _record_sent(did, key, value)
        else:
            dedup_skip += 1

    # ── Phase 3: DEPENDENT items (extract from walk cache) ────────────────────
    for item in dep_items:
        master_key = item.get("master_key", "")
        walk_extract_oid = item.get("walk_extract_oid", "")
        walk_extract_mode = item.get("walk_extract_mode", "0")
        target_key_raw = item.get("target_key_raw") or item.get("target_key", "")
        lld_macros: dict[str, str] = item.get("lld_macros") or {}

        if not master_key or not walk_extract_oid:
            continue

        walk_result = device_walk_cache.get(master_key, {})
        if not walk_result:
            # Walk ran but returned nothing, or walk is on a different poll_class
            log.debug(f"Walk cache miss for {did}/{master_key} — dependent item {target_key_raw!r} skipped")
            continue

        has_lld = "{#" in target_key_raw
        scale = item.get("scale_multiplier", 1)

        if not has_lld:
            # ── Simple DEPENDENT: single scalar at index 0 ────────────────
            value = _resolve_dependent_value(walk_result, walk_extract_oid, "0", walk_extract_mode)
            if value is None:
                # Try without any index suffix (exact OID match)
                bare = _normalize_oid(walk_extract_oid)
                value = walk_result.get(bare)
            if value is None:
                snmp_fail += 1
                continue

            try:
                value = float(value) * scale if scale != 1 else value
            except (TypeError, ValueError):
                pass

            key = item.get("target_key", target_key_raw)
            if _should_send(did, key, value):
                data[key] = value
                _record_sent(did, key, value)
            else:
                dedup_skip += 1

        else:
            # ── LLD DEPENDENT: enumerate all instances ────────────────────
            indexes = _get_snmpindex_set(walk_result, walk_extract_oid)
            for idx in indexes:
                value = _resolve_dependent_value(walk_result, walk_extract_oid, idx, walk_extract_mode)
                if value is None:
                    continue

                try:
                    value = float(value) * scale if scale != 1 else value
                except (TypeError, ValueError):
                    pass

                # Resolve {#MACRO} placeholders in the key
                realized_key = target_key_raw
                for macro_name, macro_oid in lld_macros.items():
                    if macro_name in realized_key:
                        desc_val = _resolve_dependent_value(walk_result, macro_oid, idx, "0")
                        if desc_val is not None:
                            desc_str = re.sub(r"[^a-zA-Z0-9._-]", "_", str(desc_val).strip())
                            realized_key = realized_key.replace(macro_name, desc_str)
                        else:
                            realized_key = realized_key.replace(macro_name, f"idx_{idx}")

                # Replace any remaining {#...} macros with the index
                realized_key = re.sub(r"\{#[^}]+\}", idx, realized_key)
                realized_key = _sanitize_metric_key(realized_key)

                # Dedup cache key includes the prototype key + index to avoid cross-instance collision
                cache_key = f"{target_key_raw}:{idx}"
                if _should_send(did, cache_key, value):
                    data[realized_key] = value
                    _record_sent(did, cache_key, value)
                else:
                    dedup_skip += 1

    # ── Phase 4: LLD-indexed items (discovery[] walk + per-index GET) ─────────
    lld_items = [m for m in mapping if m.get("snmp_type") == "lld_indexed"]
    tier_total += len(lld_items)

    # Group lld_indexed items by their lld_walk_oid to minimize walks
    lld_by_walk: dict[str, list[dict]] = {}
    for item in lld_items:
        walk_oid = item.get("lld_walk_oid", "")
        if walk_oid:
            lld_by_walk.setdefault(walk_oid, []).append(item)

    for walk_oid, items_group in lld_by_walk.items():
        # Walk the discovery OID to get all {index → value} entries
        walk_result = await _snmp_bulkwalk_oids(device, [walk_oid])
        if not walk_result:
            walk_fail += 1
            continue

        # Enumerate index suffixes from the walk result
        # walk_result keys are full OIDs like "1.3.6.1.4.1.xxx.INDEX"
        base_normalized = _normalize_oid(walk_oid)
        indices: list[str] = []
        for full_oid in walk_result.keys():
            norm = _normalize_oid(full_oid)
            if norm.startswith(base_normalized + "."):
                idx = norm[len(base_normalized) + 1:]
                if idx:
                    indices.append(idx)

        if not indices:
            log.debug(f"[lld_indexed] {did}: walk {walk_oid} returned no indices")
            snmp_fail += 1
            continue

        log.debug(f"[lld_indexed] {did}: discovered {len(indices)} indices from walk {walk_oid}")

        # For each item prototype, GET column_oid.INDEX for each index
        for item in items_group:
            col_oid = item.get("snmp_oid", "")
            key_raw = item.get("key_raw", item.get("key", ""))
            scale = item.get("scale_multiplier", 1)
            if not col_oid:
                continue

            for idx in indices:
                target_oid = f"{col_oid.rstrip('.')}.{idx}"
                raw, gerr = await _snmp_get(device.ip, target_oid, device)
                if raw is None:
                    snmp_fail += 1
                    continue

                try:
                    value = float(raw) * scale if scale != 1 else raw
                except (TypeError, ValueError):
                    value = raw

                # Build realized key: vmwVMState.[{#SNMPINDEX}] → vmwVMState_1
                realized_key = re.sub(r"\{#SNMPINDEX\}", idx, key_raw, flags=re.IGNORECASE)
                realized_key = re.sub(r"\{#[^}]+\}", idx, realized_key)
                realized_key = _sanitize_metric_key(realized_key)

                cache_key = f"{key_raw}:{idx}"
                if _should_send(did, cache_key, value):
                    data[realized_key] = value
                    _record_sent(did, cache_key, value)
                else:
                    dedup_skip += 1

    # ── Diagnostics ───────────────────────────────────────────────────────────
    tier_diag: dict[str, Any] = {
        "profile_id": profile.profile_id,
        "ip": device.ip,
        "tier_total": tier_total,

        "walk_items": len(walk_items),
        "walk_failed": walk_fail,
        "get_items": len(get_items),
        "macro_skipped": macro_skip,
        "snmp_failed": snmp_fail,
        "dependent_items": len(dep_items),
        "range_skipped": range_skip,
        "dedup_skipped": dedup_skip,
        "values_published": len(data),
        "walk_cache_masters": list(device_walk_cache.keys()),
        "mqtt_ok": False,
    }
    if data:
        tier_diag["sample_keys"] = _preview_keys(data)
    if error_samples:
        tier_diag["snmp_error_samples"] = error_samples
    poll_diag.record_tier(did, poll_class, tier_diag)

    if tier_total == 0:
        log.debug(
            f"[poll {poll_class}] {did}: no mapping rows for this tier. "
            f"(only fast/slow/inventory classes are polled here)."
        )
    elif not data:
        if walk_fail > 0 and len(walk_items) > 0 and walk_fail == len(walk_items):
            log.warning(
                f"[poll {poll_class}] {did} @ {device.ip}: all SNMP BULKWALKs failed ({walk_fail} walk masters). "
                f"Check SNMP, firewall, UDP/161."
            )
        elif macro_skip == len(get_items) and not walk_items and not dep_items:
            log.warning(
                f"[poll {poll_class}] {did} profile={profile.profile_id}: "
                f"all {len(get_items)} items have LLD macros in OID — cannot SNMP GET. "
                f"Re-import the template to get walk+dependent items."
            )
        elif snmp_fail > 0 and snmp_fail == (len(get_items) - macro_skip):
            sample_txt = ""
            if error_samples:
                sample_txt = (
                    f" e.g. {error_samples[0].get('target_key', '?')}: "
                    f"{error_samples[0].get('error', '')[:180]}"
                )
            log.warning(
                f"[poll {poll_class}] {did} @ {device.ip}: "
                f"every SNMP GET failed ({snmp_fail} tries).{sample_txt} "
                f"Check community or SNMPv3 creds, firewall, routing."
            )
        elif dedup_skip > 0 and snmp_fail == 0 and macro_skip == 0 and walk_fail == 0:
            log.debug(
                f"[poll {poll_class}] {did}: {dedup_skip} values unchanged (dedup/keepalive)."
            )

    if not data:
        return

    envelope = _build_envelope(
        "metrics",
        device,
        data,
        clock,
        extras={"metrics_tier": poll_class},
    )
    topic = "metrics.fast" if poll_class == "fast" else "metrics.slow"
    ok = mqtt_client.publish(topic, envelope)
    post_diag: dict[str, Any] = {**tier_diag, "mqtt_ok": ok, "values_published": len(data)}
    if data:
        post_diag["sample_keys"] = _preview_keys(data)
    poll_diag.record_tier(did, poll_class, post_diag)
    log.info(
        f"Published {len(data)} metrics ({poll_class}) for {did} → MQTT {topic} "
        f"({'sent' if ok else 'queued/offline'})"
    )

    # ── Alert evaluation ───────────────────────────────────────────────────────
    try:
        from core.alert_publisher import evaluate_and_publish
        n_alerts = evaluate_and_publish(
            device_id=did,
            device_ip=device.ip,
            profile_id=profile.profile_id,
            metrics=data,
            publish_fn=mqtt_client.publish,
        )
        if n_alerts:
            log.info(f"Alert check: {n_alerts} event(s) published for {did}")
    except Exception as _ae:
        log.debug(f"Alert publisher error: {_ae}")



# ──────────────────────────────────────────────────────────────────────────────
# Inventory poll — same 3-phase approach
# ──────────────────────────────────────────────────────────────────────────────
async def poll_inventory(device: Device) -> None:
    """Collect inventory snapshot and publish via MQTT."""
    did = device.device_id
    with get_session() as s:
        profile = _get_profile_by_slug(s, device.profile_id)
    if not profile:
        poll_diag.record_tier(
            did, "inventory", {"error": "no_profile", "tier_total": 0}
        )
        return

    try:
        full_mapping = json.loads(profile.output_mapping)
    except Exception:
        poll_diag.record_tier(
            did, "inventory", {"error": "bad_json_mapping", "tier_total": 0}
        )
        return

    mapping = [m for m in full_mapping if m.get("poll_class") == "inventory"]
    walk_items = [m for m in mapping if m.get("snmp_type") == "walk"]
    get_items = [m for m in mapping if m.get("snmp_type", "get") == "get"]
    dep_items = [m for m in mapping if m.get("snmp_type") == "dependent"]

    clock = int(time.time())
    data: dict[str, Any] = {}
    tier_total = len(walk_items) + len(get_items) + len(dep_items)
    macro_skip = 0
    walk_fail = 0
    snmp_fail = 0
    inv_error_samples: list[dict[str, str]] = []

    device_walk_cache = _walk_cache.setdefault(did, {})

    # Phase 1: Walk
    for item in walk_items:
        walk_oids = item.get("walk_oids") or []
        master_key = item.get("target_key", "")
        if not walk_oids or not master_key:
            continue
        walk_result = await _snmp_bulkwalk_oids(device, walk_oids)
        if walk_result:
            device_walk_cache[master_key] = walk_result
        else:
            walk_fail += 1

    # Phase 2: Scalar GET
    for item in get_items:
        oid = item.get("source_oid", "")
        key = item.get("target_key", "")
        if not oid or not key:
            continue
        if poll_diag.oid_has_lld_macro(oid):
            macro_skip += 1
            continue
        raw, gerr = await _snmp_get(device.ip, oid, device)
        if raw is not None:
            data[key] = raw
        else:
            snmp_fail += 1
            if len(inv_error_samples) < _MAX_ERROR_SAMPLES:
                inv_error_samples.append({"target_key": key, "oid": oid, "error": gerr or "unknown"})

    # Phase 3: Dependent
    for item in dep_items:
        master_key = item.get("master_key", "")
        walk_extract_oid = item.get("walk_extract_oid", "")
        walk_extract_mode = item.get("walk_extract_mode", "0")
        target_key_raw = item.get("target_key_raw") or item.get("target_key", "")
        lld_macros: dict[str, str] = item.get("lld_macros") or {}

        if not master_key or not walk_extract_oid:
            continue
        walk_result = device_walk_cache.get(master_key, {})
        if not walk_result:
            continue

        has_lld = "{#" in target_key_raw
        if not has_lld:
            value = _resolve_dependent_value(walk_result, walk_extract_oid, "0", walk_extract_mode)
            if value is None:
                value = walk_result.get(_normalize_oid(walk_extract_oid))
            if value is not None:
                data[item.get("target_key", target_key_raw)] = value
            else:
                snmp_fail += 1
        else:
            indexes = _get_snmpindex_set(walk_result, walk_extract_oid)
            for idx in indexes:
                value = _resolve_dependent_value(walk_result, walk_extract_oid, idx, walk_extract_mode)
                if value is None:
                    continue
                realized_key = target_key_raw
                for macro_name, macro_oid in lld_macros.items():
                    if macro_name in realized_key:
                        desc_val = _resolve_dependent_value(walk_result, macro_oid, idx, "0")
                        if desc_val is not None:
                            desc_str = re.sub(r"[^a-zA-Z0-9._-]", "_", str(desc_val).strip())
                            realized_key = realized_key.replace(macro_name, desc_str)
                        else:
                            realized_key = realized_key.replace(macro_name, f"idx_{idx}")
                realized_key = re.sub(r"\{#[^}]+\}", idx, realized_key)
                realized_key = _sanitize_metric_key(realized_key)
                data[realized_key] = value

    inv_pre: dict[str, Any] = {
        "profile_id": profile.profile_id,
        "ip": device.ip,
        "tier_total": tier_total,
        "walk_failed": walk_fail,
        "macro_skipped": macro_skip,
        "snmp_failed": snmp_fail,
        "values_published": len(data),
        "mqtt_ok": False,
    }
    if data:
        inv_pre["sample_keys"] = _preview_keys(data)
    if inv_error_samples:
        inv_pre["snmp_error_samples"] = inv_error_samples
    poll_diag.record_tier(did, "inventory", inv_pre)

    if tier_total > 0 and not data:
        if walk_fail == len(walk_items) and len(walk_items) > 0:
            log.warning(f"[poll inventory] {did}: all SNMP BULKWALKs failed.")
        elif snmp_fail == (len(get_items) - macro_skip) and len(get_items) > macro_skip:
            log.warning(f"[poll inventory] {did} @ {device.ip}: all inventory SNMP GETs failed.")

    if not data:
        return

    # Cache inventory locally
    with get_session() as s:
        cache = s.get(InventoryCache, device.device_id)
        if cache:
            cache.data_json = json.dumps(data)
        else:
            s.add(InventoryCache(device_id=device.device_id, data_json=json.dumps(data)))
        s.commit()

    envelope = _build_envelope("inventory", device, data, clock)
    ok = mqtt_client.publish("inventory", envelope)
    inv_post: dict[str, Any] = {**inv_pre, "mqtt_ok": ok, "values_published": len(data)}
    if data:
        inv_post["sample_keys"] = _preview_keys(data)
    if inv_error_samples:
        inv_post["snmp_error_samples"] = inv_error_samples
    poll_diag.record_tier(did, "inventory", inv_post)
    log.info(
        f"Published inventory for {did} ({len(data)} keys) → MQTT "
        f"({'sent' if ok else 'queued/offline'})"
    )


# ──────────────────────────────────────────────────────────────────────────────
# Polling loop
# ──────────────────────────────────────────────────────────────────────────────
async def run_poller() -> None:
    """
    Main polling loop. Runs indefinitely.
    Polls all active devices on their respective intervals.
    """
    log.info("SNMP poller started (v5.2 — walk+get+dependent)")
    _fast_counters: dict[str, float] = {}
    _slow_counters: dict[str, float] = {}
    _inv_counters: dict[str, float] = {}

    while True:
        if _polling_paused:
            await asyncio.sleep(5)
            continue

        now = time.time()
        with get_session() as s:
            devices = s.exec(select(Device).where(Device.status == "active")).all()

        global _immediate_inventory, _immediate_metrics_fast, _immediate_metrics_slow
        do_inv = _immediate_inventory
        do_fast = _immediate_metrics_fast
        do_slow = _immediate_metrics_slow
        if do_inv:
            _immediate_inventory = False
        if do_fast:
            _immediate_metrics_fast = False
        if do_slow:
            _immediate_metrics_slow = False

        tasks = []
        for device in devices:
            did = device.device_id
            fast_due = (now - _fast_counters.get(did, 0)) >= device.poll_interval_fast
            slow_due = (now - _slow_counters.get(did, 0)) >= device.poll_interval_slow
            inv_due = (now - _inv_counters.get(did, 0)) >= device.poll_interval_inventory

            if do_fast:
                fast_due = True
            if do_slow:
                slow_due = True
            if do_inv:
                inv_due = True

            if fast_due:
                tasks.append(poll_device(device, "fast"))
                _fast_counters[did] = now
            if slow_due:
                tasks.append(poll_device(device, "slow"))
                _slow_counters[did] = now
            if inv_due:
                tasks.append(poll_inventory(device))
                _inv_counters[did] = now

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        await asyncio.sleep(10)  # tick every 10 seconds
