"""
Alert publisher for NOCKO Proxy Agent.

Evaluates collected SNMP metric values against known alert thresholds
and publishes events to the MQTT `events` topic when problems are detected.

Alert lifecycle:
  PROBLEM  — published when threshold is first exceeded
  RESOLVED — published when value returns to normal
  (no repeat spam: uses per-device state cache)

Supported alert domains:
  - Physical disk state (Dell iDRAC: dellDiskState)
  - RAID virtual disk state (Dell iDRAC: dellVDiskState)
  - Hardware subsystem status (ESXi/iDRAC: vmwSubsystemStatus)
  - PSU status (Dell iDRAC: dellPSUStatus)
  - Fan status (Dell iDRAC: dellFanStatus)
  - Temperature status (Dell iDRAC: dellTempStatus + reading)

Events topic: nocko/{tenant_id}/{agent_id}/events
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from core.logger import log

# ──────────────────────────────────────────────────────────────────────────────
# Threshold definitions
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class AlertRule:
    """Defines when a metric value constitutes a problem."""
    key_prefix: str          # Matches metric keys starting with this prefix
    severity: str            # critical | warning | info
    label: str               # Human-readable alert name
    check_fn: Any            # callable(value) -> (is_problem: bool, detail: str)


def _disk_state_check(val):
    """Dell iDRAC physicalDiskState: 1=ready 2=failed 3=online 6=degraded 26=predictiveFailure 35=rebuilding"""
    try:
        v = int(float(val))
    except (TypeError, ValueError):
        return False, ""
    STATE_MAP = {
        2:  ("FAILED",             "critical"),
        6:  ("DEGRADED",           "critical"),
        26: ("PREDICTIVE FAILURE", "warning"),
        35: ("REBUILDING",         "info"),
        11: ("REMOVED",            "warning"),
    }
    if v in STATE_MAP:
        label, _ = STATE_MAP[v]
        return True, f"state code {v} ({label})"
    return False, ""


def _vdisk_state_check(val):
    """Dell iDRAC virtualDiskState"""
    try:
        v = int(float(val))
    except (TypeError, ValueError):
        return False, ""
    BAD = {2: "FAILED", 6: "DEGRADED", 15: "FOREIGN", 35: "REBUILDING"}
    if v in BAD:
        return True, f"state code {v} ({BAD[v]})"
    return False, ""


def _dell_status_check(val):
    """Generic Dell status: 3=ok 4=nonCritical 5=critical 6=nonRecoverable"""
    try:
        v = int(float(val))
    except (TypeError, ValueError):
        return False, ""
    if v == 4:
        return True, "non-critical"
    if v >= 5:
        return True, f"critical/failed (status {v})"
    return False, ""


def _vmw_subsystem_check(val):
    """VMware ESXi subsystem status: 2=normal 3=marginal 4=critical 5=failed"""
    try:
        v = int(float(val))
    except (TypeError, ValueError):
        return False, ""
    if v == 3:
        return True, "marginal"
    if v >= 4:
        return True, f"critical/failed (status {v})"
    return False, ""


def _temp_high_check(val):
    """Temperature reading alert at >50°C"""
    try:
        v = float(val)
    except (TypeError, ValueError):
        return False, ""
    if v > 60:
        return True, f"temperature critical: {v}°C (>60°C)"
    if v > 50:
        return True, f"temperature high: {v}°C (>50°C)"
    return False, ""


# Registry of alert rules (checked in order)
_ALERT_RULES: list[AlertRule] = [
    AlertRule("dellDiskState",        "critical", "Physical disk problem",   _disk_state_check),
    AlertRule("dellVDiskState",       "critical", "RAID array problem",      _vdisk_state_check),
    AlertRule("dellPSUStatus",        "critical", "Power supply problem",    _dell_status_check),
    AlertRule("dellFanStatus",        "critical", "Fan problem",             _dell_status_check),
    AlertRule("dellTempStatus",       "critical", "Temperature sensor",      _dell_status_check),
    AlertRule("dellTempReading",      "warning",  "Temperature high",        _temp_high_check),
    AlertRule("dellCpuStatus",        "critical", "CPU problem",             _dell_status_check),
    AlertRule("dellMemStatus",        "critical", "Memory DIMM problem",     _dell_status_check),
    AlertRule("vmwSubsystemStatus",   "critical", "ESXi subsystem problem",  _vmw_subsystem_check),
    AlertRule("dellSysPrimaryStatus", "critical", "Server overall health",   _dell_status_check),
]

# ──────────────────────────────────────────────────────────────────────────────
# State cache — tracks active alerts to avoid repeat publishing
# Format: {f"{device_id}:{metric_key}": "problem"|"ok"}
# ──────────────────────────────────────────────────────────────────────────────
_alert_state: dict[str, str] = {}


# ──────────────────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────────────────

def evaluate_and_publish(
    device_id: str,
    device_ip: str,
    profile_id: str,
    metrics: dict[str, Any],
    publish_fn,          # callable(topic_suffix, payload_dict)
) -> int:
    """
    Check collected metrics against alert rules.
    Publishes PROBLEM/RESOLVED events to MQTT events topic.
    Returns number of alerts published.
    """
    published = 0

    for metric_key, value in metrics.items():
        rule = _find_rule(metric_key)
        if rule is None:
            continue

        is_problem, detail = rule.check_fn(value)
        cache_key = f"{device_id}:{metric_key}"
        prev_state = _alert_state.get(cache_key, "ok")

        if is_problem and prev_state == "ok":
            # New problem — publish PROBLEM event
            _publish_event(
                publish_fn=publish_fn,
                event_type="PROBLEM",
                severity=rule.severity,
                device_id=device_id,
                device_ip=device_ip,
                profile_id=profile_id,
                metric_key=metric_key,
                value=value,
                label=rule.label,
                detail=detail,
            )
            _alert_state[cache_key] = "problem"
            published += 1
            log.warning(
                f"ALERT [{rule.severity.upper()}] {device_id}/{metric_key}={value} — {rule.label}: {detail}"
            )

        elif not is_problem and prev_state == "problem":
            # Recovered — publish RESOLVED event
            _publish_event(
                publish_fn=publish_fn,
                event_type="RESOLVED",
                severity="info",
                device_id=device_id,
                device_ip=device_ip,
                profile_id=profile_id,
                metric_key=metric_key,
                value=value,
                label=rule.label,
                detail="returned to normal",
            )
            _alert_state[cache_key] = "ok"
            published += 1
            log.info(f"RESOLVED {device_id}/{metric_key} — {rule.label}")

    return published


def get_active_alerts(device_id: str = "") -> list[dict]:
    """Return list of currently active (unresolved) alerts, optionally filtered by device."""
    result = []
    for cache_key, state in _alert_state.items():
        if state == "problem":
            if device_id and not cache_key.startswith(f"{device_id}:"):
                continue
            dev, _, metric = cache_key.partition(":")
            result.append({"device_id": dev, "metric_key": metric})
    return result


# ──────────────────────────────────────────────────────────────────────────────
# Internals
# ──────────────────────────────────────────────────────────────────────────────

def _find_rule(metric_key: str) -> AlertRule | None:
    """Find first matching alert rule for a metric key."""
    for rule in _ALERT_RULES:
        if metric_key.startswith(rule.key_prefix):
            return rule
    return None


def _publish_event(
    publish_fn,
    event_type: str,
    severity: str,
    device_id: str,
    device_ip: str,
    profile_id: str,
    metric_key: str,
    value: Any,
    label: str,
    detail: str,
) -> None:
    """Build and publish an event envelope to the MQTT events topic."""
    payload = {
        "schema_version": "1.0",
        "payload_type": "event",
        "records": [{
            "clock": int(time.time()),
            "event_type": event_type,           # PROBLEM | RESOLVED
            "severity": severity,               # critical | warning | info
            "device_id": device_id,
            "device_ip": device_ip,
            "profile_id": profile_id,
            "metric_key": metric_key,
            "value": str(value),
            "label": label,
            "detail": detail,
        }],
    }
    try:
        publish_fn("events", payload)
        log.debug(f"Event published: {event_type} {device_id}/{metric_key}")
    except Exception as e:
        log.warning(f"Failed to publish alert event: {e}")
