"""
SNMP Poller for NOCKO Proxy Agent.

Polls devices according to poll_class (fast / slow / inventory / lld).
Produces Payload Contract envelopes (proxy_agent_tz.md Section 7).

Supports: SNMPv2c and SNMPv3 (authPriv).
Library: puresnmp (pure-Python, no net-snmp dependency).
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

import puresnmp

from core.config import config
from core.database import Device, DeviceProfile, InventoryCache, get_session
from core.logger import log
from core.mqtt_client import mqtt_client
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


# ──────────────────────────────────────────────────────────────────────────────
# SNMP helpers
# ──────────────────────────────────────────────────────────────────────────────
async def _snmp_get(ip: str, oid: str, device: Device) -> Any:
    """Single SNMP GET. Returns the value or None on error."""
    try:
        if device.snmp_version == "3":
            credentials = puresnmp.V3SEC(
                username=device.snmp_v3_user,
                auth_passwd=device.snmp_v3_auth_key,
                priv_passwd=device.snmp_v3_priv_key,
            )
            result = await puresnmp.aioget(ip, credentials, oid)
        else:
            result = await puresnmp.aioget(ip, device.snmp_community, oid)
        return result
    except Exception as e:
        log.debug(f"SNMP GET {ip} {oid}: {e}")
        return None


async def _snmp_walk(ip: str, base_oid: str, device: Device) -> dict[str, Any]:
    """SNMP WALK. Returns {oid_suffix: value} dict."""
    try:
        if device.snmp_version == "3":
            credentials = puresnmp.V3SEC(
                username=device.snmp_v3_user,
                auth_passwd=device.snmp_v3_auth_key,
                priv_passwd=device.snmp_v3_priv_key,
            )
            rows = await puresnmp.aiobulkwalk(ip, credentials, base_oid)
        else:
            rows = await puresnmp.aiobulkwalk(ip, device.snmp_community, base_oid)
        return {str(oid): val for oid, val in rows}
    except Exception as e:
        log.debug(f"SNMP WALK {ip} {base_oid}: {e}")
        return {}


# ──────────────────────────────────────────────────────────────────────────────
# Payload builder (Section 7 envelope format)
# ──────────────────────────────────────────────────────────────────────────────
def _build_envelope(
    payload_type: str,
    device: Device,
    data: dict,
    clock: int,
    *,
    extras: dict[str, Any] | None = None,
) -> dict:
    """
    Portal / storage TZ: envelope payload_type is metrics | inventory | events | heartbeat.
    For SNMP tiers we use payload_type \"metrics\" + metrics_tier fast|slow (MQTT topic stays metrics.fast/slow).
    """
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
# Single device poll
# ──────────────────────────────────────────────────────────────────────────────
async def poll_device(device: Device, poll_class: str) -> None:
    """Poll a single device for the given poll_class."""
    with get_session() as s:
        profile = _get_profile_by_slug(s, device.profile_id)
    if not profile:
        log.warning(f"Device {device.device_id} has no profile, skipping poll")
        return

    try:
        mapping = json.loads(profile.output_mapping)
    except Exception:
        log.error(f"Invalid output_mapping for profile {device.profile_id}")
        return

    clock = int(time.time())
    data: dict[str, Any] = {}

    for item in mapping:
        if item.get("poll_class") != poll_class:
            continue
        oid = item.get("source_oid", "")
        key = item.get("target_key", "")
        if not oid or not key:
            continue

        raw = await _snmp_get(device.ip, oid, device)
        if raw is None:
            continue

        # Apply scale_multiplier
        scale = item.get("scale_multiplier", 1)
        try:
            value = float(raw) * scale if scale != 1 else raw
        except (TypeError, ValueError):
            value = raw

        # Validate range
        vrange = item.get("valid_range")
        if vrange and isinstance(value, (int, float)):
            lo, hi = vrange.get("min", float("-inf")), vrange.get("max", float("inf"))
            if not (lo <= value <= hi):
                log.debug(f"Value {value} out of range [{lo},{hi}] for {key}, skipping")
                continue

        if _should_send(device.device_id, key, value):
            data[key] = value
            _record_sent(device.device_id, key, value)

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
    mqtt_client.publish(topic, envelope)
    log.debug(f"Published {len(data)} metrics ({poll_class}) for {device.device_id}")


# ──────────────────────────────────────────────────────────────────────────────
# Inventory poll
# ──────────────────────────────────────────────────────────────────────────────
async def poll_inventory(device: Device) -> None:
    """Collect inventory snapshot and publish via MQTT."""
    with get_session() as s:
        profile = _get_profile_by_slug(s, device.profile_id)
    if not profile:
        return

    mapping = json.loads(profile.output_mapping) if profile else []
    clock = int(time.time())
    data: dict[str, Any] = {}

    for item in mapping:
        if item.get("poll_class") != "inventory":
            continue
        raw = await _snmp_get(device.ip, item["source_oid"], device)
        if raw is not None:
            data[item["target_key"]] = raw

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
    mqtt_client.publish("inventory", envelope)
    log.info(f"Published inventory for {device.device_id}")


# ──────────────────────────────────────────────────────────────────────────────
# Polling loop
# ──────────────────────────────────────────────────────────────────────────────
async def run_poller() -> None:
    """
    Main polling loop. Runs indefinitely.
    Polls all active devices on their respective intervals.
    """
    log.info("SNMP poller started")
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
