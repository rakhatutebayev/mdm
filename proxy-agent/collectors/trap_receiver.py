"""
SNMP Trap Receiver for NOCKO Proxy Agent.

Listens on UDP :162 for incoming SNMP traps.
Write-ahead to TrapArchive before forwarding.
Anti-storm: max 10 traps/sec per source IP.

Sends traps immediately via MQTT events topic (QoS 1).
Based on proxy_agent_tz.md Section 2.7 and payload Section 7.5.
"""
from __future__ import annotations

import asyncio
import json
import time
from collections import defaultdict
from datetime import datetime

from core.database import TrapArchive, get_session
from core.logger import log
from core.mqtt_client import mqtt_client
from core.config import config

# Anti-storm: max traps per source per second
_MAX_TRAPS_PER_IP_PER_SEC = 10
_storm_counters: dict[str, list[float]] = defaultdict(list)


def _is_storm(source_ip: str) -> bool:
    now = time.time()
    timestamps = _storm_counters[source_ip]
    # Keep only last second
    _storm_counters[source_ip] = [t for t in timestamps if now - t < 1.0]
    _storm_counters[source_ip].append(now)
    return len(_storm_counters[source_ip]) > _MAX_TRAPS_PER_IP_PER_SEC


class TrapReceiverProtocol(asyncio.DatagramProtocol):
    """asyncio UDP protocol for receiving raw SNMP traps."""

    def __init__(self) -> None:
        self._transport: asyncio.DatagramTransport | None = None

    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self._transport = transport
        log.info("Trap receiver listening on UDP :162")

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        source_ip = addr[0]

        # Anti-storm check
        if _is_storm(source_ip):
            log.warning(f"Trap storm detected from {source_ip}, dropping")
            return

        # Attempt minimal PDU decode — just extract OID string from raw bytes
        oid = _extract_oid_from_raw(data)
        trap_dict = {
            "oid": oid,
            "source_ip": source_ip,
            "raw_hex": data.hex(),
        }

        # Write-ahead to TrapArchive BEFORE forwarding
        archive_id = _archive_trap(oid, source_ip, trap_dict)

        # Build events envelope (Section 7.5)
        envelope = _build_event_envelope(source_ip, oid, trap_dict)

        # Publish via MQTT (QoS 1 — traps bypass batch)
        ok = mqtt_client.publish("events", envelope, qos=1)
        if ok:
            _mark_forwarded(archive_id)
        else:
            log.debug(f"Trap queued (MQTT offline) from {source_ip}")

    def error_received(self, exc: Exception) -> None:
        log.error(f"Trap receiver error: {exc}")


def _extract_oid_from_raw(data: bytes) -> str:
    """
    Very lightweight OID extraction from raw SNMP PDU bytes.
    Returns dotted OID string or 'unknown' if not parseable.
    This is intentionally minimal — full parsing is expensive.
    """
    try:
        # OID typically starts after the initial SNMP header bytes
        # Look for OID tag 0x06 in the packet
        idx = data.find(b'\x06')
        if idx >= 0 and idx + 1 < len(data):
            length = data[idx + 1]
            oid_bytes = data[idx + 2: idx + 2 + length]
            parts = [str(b) for b in oid_bytes]
            return "1.3." + ".".join(parts[1:]) if parts else "unknown"
    except Exception:
        pass
    return "unknown"


def _archive_trap(oid: str, source_ip: str, raw_dict: dict) -> int | None:
    """Persist trap to TrapArchive. Returns row id or None on error."""
    try:
        with get_session() as s:
            entry = TrapArchive(
                oid=oid,
                source_ip=source_ip,
                raw_data=json.dumps(raw_dict),
            )
            s.add(entry)
            s.commit()
            s.refresh(entry)
            return entry.id
    except Exception as e:
        log.error(f"TrapArchive write error: {e}")
        return None


def _mark_forwarded(archive_id: int | None) -> None:
    if archive_id is None:
        return
    try:
        with get_session() as s:
            entry = s.get(TrapArchive, archive_id)
            if entry:
                entry.forwarded_at = datetime.utcnow()
                s.commit()
    except Exception as e:
        log.error(f"TrapArchive update error: {e}")


def _build_event_envelope(source_ip: str, oid: str, trap_dict: dict) -> dict:
    return {
        "schema_version": "1.0",
        "tenant_id": config.server.tenant_id or "",
        "agent_id": config.server.agent_id or "",
        "sent_at": int(time.time()),
        "payload_type": "events",
        "records": [{
            "device_uid": source_ip,       # server resolves IP → device_uid
            "clock": int(time.time()),
            "event_type": "trap",
            "source": oid,
            "severity": "info",            # server applies threshold rules
            "code": "",
            "message": f"SNMP trap from {source_ip} OID={oid}",
            "item_key": None,
        }],
    }


async def run_trap_receiver(port: int = 162) -> None:
    """Start the UDP trap receiver. Requires root or CAP_NET_BIND_SERVICE for :162."""
    loop = asyncio.get_running_loop()
    try:
        transport, _ = await loop.create_datagram_endpoint(
            TrapReceiverProtocol,
            local_addr=("0.0.0.0", port),
        )
        log.info(f"Trap receiver started on UDP :{port}")
        # Keep running until cancelled
        try:
            await asyncio.sleep(float("inf"))
        finally:
            transport.close()
    except PermissionError:
        log.warning(
            f"Cannot bind UDP :{port} (permission denied). "
            "Run as root or use authbind / CAP_NET_BIND_SERVICE. Trap receiver disabled."
        )
    except Exception as e:
        log.error(f"Trap receiver startup error: {e}")
