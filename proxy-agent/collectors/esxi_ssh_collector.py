"""
ESXi SSH Collector — собирает данные об оборудовании ESXi-хоста через SSH:
  - Физические диски (perccli / PERC H710/H310)
  - RAID Virtual Drives
  - CPU / RAM
  - Сетевые интерфейсы
  - Хранилища (datastore)
  - Платформа (модель, S/N)

Запускается параллельно с основным агентом и публикует данные в MQTT
используя тот же envelope-формат что и snmp_poller.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

log = logging.getLogger("esxi_ssh")

# ── SSH helper ──────────────────────────────────────────────────────────────────


async def _ssh_run(host: str, user: str, password: str, cmd: str, timeout: int = 20) -> str:
    """Run a shell command on remote ESXi host via SSH and return stdout."""
    proc = await asyncio.create_subprocess_exec(
        "sshpass", "-p", password,
        "ssh", "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=10",
        "-o", "BatchMode=no",
        f"{user}@{host}", cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"SSH command timed out after {timeout}s: {cmd[:60]}")
    return stdout.decode("utf-8", errors="replace")


# ── perccli parsers ─────────────────────────────────────────────────────────────


def _parse_perccli_pd(output: str) -> dict[str, Any]:
    """Parse perccli /c0/eall/sall show all output into keyed metrics."""
    data: dict[str, Any] = {}
    slot_key = None
    current: dict = {}

    # Parse slot headers like "Drive /c0/e32/s2 State :"
    for line in output.splitlines():
        # New drive section
        m = re.match(r"Drive\s+/c0/e(\d+)/s(\d+)\s*:", line)
        if m:
            if slot_key and current:
                _flush_disk(data, slot_key, current)
            eid, slt = m.group(1), m.group(2)
            slot_key = f"e{eid}s{slt}"
            current = {"eid": int(eid), "slot": int(slt)}
            continue

        # Table row: EID:Slt DID State ...
        m2 = re.match(
            r"\s*(\d+):(\d+)\s+(\d+)\s+(\w+)\s+(\S+)\s+([\d.]+\s+\w+)\s+(\w+)\s+(\w+)",
            line,
        )
        if m2 and slot_key:
            state = m2.group(4)
            current["state"] = state
            current["intf"] = m2.group(7)
            current["media"] = m2.group(8)
            continue

        # Key: value pairs
        if "=" in line and slot_key:
            k, _, v = line.partition("=")
            k = k.strip().lower().replace(" ", "_")
            v = v.strip()
            if k in ("media_error_count", "other_error_count",
                      "predictive_failure_count", "shield_counter"):
                try:
                    current[k] = int(v)
                except ValueError:
                    pass
            elif k == "drive_temperature":
                m3 = re.search(r"(\d+)C", v)
                if m3:
                    current["temperature_c"] = int(m3.group(1))
            elif k == "s.m.a.r.t_alert_flagged_by_drive":
                current["smart_alert"] = 0 if v.lower() == "no" else 1
            elif k == "model_number":
                current["model"] = v
            elif k == "sn":
                current["serial"] = v
            elif k == "firmware_revision":
                current["firmware"] = v
            elif k in ("device_speed", "link_speed"):
                current[k] = v

    if slot_key and current:
        _flush_disk(data, slot_key, current)

    return data


def _flush_disk(data: dict, slot_key: str, info: dict) -> None:
    """Write collected disk info as flat metrics keys."""
    ok_states = {"onln", "online", "ugood", "hotsp", "dhs", "ghs"}
    state = info.get("state", "unknown").lower()
    status_val = 1 if state in ok_states else 0

    pfx = f"pd_{slot_key}"
    data[f"{pfx}.state"] = state
    data[f"{pfx}.status_ok"] = status_val
    data[f"{pfx}.model"] = info.get("model", "")
    data[f"{pfx}.serial"] = info.get("serial", "")
    data[f"{pfx}.firmware"] = info.get("firmware", "")
    data[f"{pfx}.interface"] = info.get("intf", "")
    data[f"{pfx}.media"] = info.get("media", "")
    data[f"{pfx}.temperature_c"] = info.get("temperature_c", -1)
    data[f"{pfx}.media_errors"] = info.get("media_error_count", 0)
    data[f"{pfx}.other_errors"] = info.get("other_error_count", 0)
    data[f"{pfx}.predictive_failures"] = info.get("predictive_failure_count", 0)
    data[f"{pfx}.smart_alert"] = info.get("smart_alert", 0)


def _parse_perccli_vd(output: str) -> dict[str, Any]:
    """Parse virtual drive table from perccli /c0/vall show."""
    data: dict[str, Any] = {}
    vd_index = None
    for line in output.splitlines():
        m = re.match(r"\s*(\d+)/(\d+)\s+(\w+[-\w]*)\s+(\w+)\s+(\w+)", line)
        if m:
            vd_index = int(m.group(2))
            pfx = f"vd{vd_index}"
            data[f"{pfx}.raid_level"] = m.group(3)
            state = m.group(4).lower()
            data[f"{pfx}.state"] = state
            data[f"{pfx}.status_ok"] = 1 if state == "optl" else 0
        # Size
        if vd_index is not None and "Size" in line:
            m2 = re.search(r"([\d.]+)\s*(GB|MB|TB)", line, re.IGNORECASE)
            if m2:
                sz = float(m2.group(1))
                unit = m2.group(2).upper()
                if unit == "TB":
                    sz *= 1024
                elif unit == "MB":
                    sz /= 1024
                data[f"vd{vd_index}.size_gb"] = sz
    return data


# ── esxcli parsers ──────────────────────────────────────────────────────────────


def _parse_platform(output: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower()
        v = v.strip()
        if "product name" in k:
            data["hw.model"] = v
        elif "vendor name" in k:
            data["hw.vendor"] = v
        elif "serial number" in k and "enclosure" not in k:
            data["hw.serial"] = v
        elif "uuid" in k:
            data["hw.uuid"] = v
    return data


def _parse_cpu(output: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in output.splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k = k.strip().lower()
        v = v.strip()
        if "cpu packages" in k:
            try:
                data["cpu.packages"] = int(v)
            except ValueError:
                pass
        elif "cpu cores" in k:
            try:
                data["cpu.cores"] = int(v)
            except ValueError:
                pass
        elif "cpu threads" in k:
            try:
                data["cpu.threads"] = int(v)
            except ValueError:
                pass
    return data


def _parse_memory(output: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in output.splitlines():
        if "Physical Memory" in line and ":" in line:
            _, _, v = line.partition(":")
            try:
                data["memory.bytes"] = int(v.strip().split()[0])
                data["memory.gb"] = round(data["memory.bytes"] / (1024 ** 3), 2)
            except ValueError:
                pass
    return data


def _parse_nics(output: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    for line in output.splitlines():
        parts = line.split()
        if len(parts) >= 6 and parts[0].startswith("vmnic"):
            name = parts[0]
            link = parts[4].lower()  # Up/Down
            try:
                speed = int(parts[5])
            except (ValueError, IndexError):
                speed = 0
            data[f"nic.{name}.link"] = link
            data[f"nic.{name}.speed_mbps"] = speed
            data[f"nic.{name}.up"] = 1 if link == "up" else 0
    return data


def _parse_datastores(output: str) -> dict[str, Any]:
    data: dict[str, Any] = {}
    idx = 0
    for line in output.splitlines():
        # Skip header
        if line.startswith("Mount Point") or line.startswith("---"):
            continue
        parts = line.split()
        if len(parts) >= 7:
            try:
                total_b = int(parts[5])
                free_b = int(parts[6])
                used_b = total_b - free_b
                pfx = f"ds{idx}"
                data[f"{pfx}.name"] = parts[1][:64]
                data[f"{pfx}.type"] = parts[4]
                data[f"{pfx}.total_gb"] = round(total_b / (1024 ** 3), 2)
                data[f"{pfx}.free_gb"] = round(free_b / (1024 ** 3), 2)
                data[f"{pfx}.used_gb"] = round(used_b / (1024 ** 3), 2)
                data[f"{pfx}.used_pct"] = round(used_b / total_b * 100, 1) if total_b else 0
                idx += 1
            except (ValueError, IndexError, ZeroDivisionError):
                pass
    return data


def _parse_smbios_memory(output: str) -> dict[str, Any]:
    """
    Parse smbiosDump output for Memory Device sections.
    Only processes slots that have memory installed (Size != 'No Memory Installed').
    Returns keys like:
      dimm.DIMM_A1.size_gb, dimm.DIMM_A1.speed_mhz, dimm.DIMM_A1.part_number,
      dimm.DIMM_A1.manufacturer, dimm.DIMM_A1.serial, dimm.DIMM_A1.type
    Additionally: memory.dimm_count, memory.dimm_total_gb
    """
    data: dict[str, Any] = {}
    current: dict = {}
    in_mem = False

    def _flush(info: dict) -> None:
        loc = info.get("location", "").strip().strip('"')
        size = info.get("size", "")
        if not loc or "No Memory Installed" in size or not size:
            return
        # Parse size: "4 GB" → 4.0
        m = re.search(r"([\d.]+)\s*(GB|MB)", size, re.IGNORECASE)
        size_gb = 0.0
        if m:
            v = float(m.group(1))
            size_gb = v if "GB" in m.group(2).upper() else v / 1024
        safe = loc.replace(" ", "_")
        pfx = f"dimm.{safe}"
        data[f"{pfx}.location"] = loc
        data[f"{pfx}.size_gb"] = size_gb
        data[f"{pfx}.manufacturer"] = info.get("manufacturer", "").strip().strip('"')
        data[f"{pfx}.part_number"] = info.get("part_number", "").strip().strip('"')
        data[f"{pfx}.serial"] = info.get("serial", "").strip().strip('"')
        data[f"{pfx}.type"] = info.get("type", "").strip()
        speed = info.get("speed", "")
        m2 = re.search(r"(\d+)\s*MHz", speed)
        data[f"{pfx}.speed_mhz"] = int(m2.group(1)) if m2 else 0

    for line in output.splitlines():
        if "Memory Device:" in line:
            if in_mem and current:
                _flush(current)
            current = {}
            in_mem = True
            continue
        if not in_mem:
            continue
        # Any non-indented line that's not a Memory Device ends this block
        if line and not line.startswith(" ") and "Memory Device" not in line:
            _flush(current)
            current = {}
            in_mem = False
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip().lower()
            v = v.strip()
            if k == "location":
                current["location"] = v
            elif k == "manufacturer":
                current["manufacturer"] = v
            elif k in ("serial", "serial number"):
                current["serial"] = v
            elif k in ("part number", "part_number"):
                current["part_number"] = v
            elif k == "size":
                current["size"] = v
            elif k == "speed":
                current["speed"] = v
            elif k == "type" and "detail" not in k:
                current["type"] = v

    if in_mem and current:
        _flush(current)

    # Aggregates
    dimm_keys = [k for k in data if k.endswith(".size_gb")]
    if dimm_keys:
        data["memory.dimm_count"] = len(dimm_keys)
        data["memory.dimm_total_gb"] = round(sum(data[k] for k in dimm_keys), 1)

    return data



# ── Envelope builder ────────────────────────────────────────────────────────────


def _build_envelope(
    payload_type: str,
    device_uid: str,
    agent_id: str,
    tenant_id: str,
    data: dict,
) -> dict:
    ts = int(time.time())
    return {
        "schema_version": "1.0",
        "tenant_id": tenant_id,
        "agent_id": agent_id,
        "sent_at": ts,
        "payload_type": payload_type,
        "records": [{
            "device_uid": device_uid,
            "clock": ts,
            "enqueue_ts": ts,
            "data": data,
        }],
    }


# ── Main collect function ───────────────────────────────────────────────────────

PERCCLI = "/opt/lsi/perccli/perccli"
PERCCLI_ENV = "export LD_LIBRARY_PATH=/opt/lsi/perccli:$LD_LIBRARY_PATH"


async def collect_esxi_device(
    device_id: str,
    host: str,
    ssh_user: str,
    ssh_password: str,
    mqtt_client,
    agent_id: str,
    tenant_id: str,
) -> None:
    """
    Collect all hardware metrics from an ESXi host via SSH and publish to MQTT.
    Call this periodically (e.g., every 300s for metrics, 3600s for inventory).
    """
    log.info(f"[esxi_ssh] {device_id} @ {host}: starting collection")
    ts = int(time.time())
    metrics_data: dict[str, Any] = {}
    inventory_data: dict[str, Any] = {}

    try:
        # ── Platform info (model, SN) ─────────────────────────────────────────
        out = await _ssh_run(host, ssh_user, ssh_password,
                             "esxcli hardware platform get", timeout=15)
        inventory_data.update(_parse_platform(out))

        # ── CPU ───────────────────────────────────────────────────────────────
        out = await _ssh_run(host, ssh_user, ssh_password,
                             "esxcli hardware cpu global get", timeout=15)
        inventory_data.update(_parse_cpu(out))

        # ── Memory ───────────────────────────────────────────────────────────
        out = await _ssh_run(host, ssh_user, ssh_password,
                             "esxcli hardware memory get", timeout=15)
        inventory_data.update(_parse_memory(out))

        # ── NICs ─────────────────────────────────────────────────────────────
        out = await _ssh_run(host, ssh_user, ssh_password,
                             "esxcli network nic list", timeout=15)
        nic_data = _parse_nics(out)
        metrics_data.update(nic_data)
        inventory_data.update({k: v for k, v in nic_data.items()
                                if k.endswith(".link") or k.endswith(".speed_mbps")})

        # ── Datastores ────────────────────────────────────────────────────────
        out = await _ssh_run(host, ssh_user, ssh_password,
                             "esxcli storage filesystem list", timeout=15)
        ds_data = _parse_datastores(out)
        metrics_data.update(ds_data)

        # ── Memory DIMMs via smbiosDump ───────────────────────────────────────
        out = await _ssh_run(host, ssh_user, ssh_password,
                             "smbiosDump 2>/dev/null", timeout=15)
        if "Memory Device" in out:
            dimm_data = _parse_smbios_memory(out)
            # Per-DIMM detail → inventory only
            inventory_data.update(dimm_data)
            # Summary metrics (count, total GB)
            for k in ("memory.dimm_count", "memory.dimm_total_gb"):
                if k in dimm_data:
                    metrics_data[k] = dimm_data[k]

        # ── Physical Disks via perccli ────────────────────────────────────────
        perccli_cmd = (
            f"{PERCCLI_ENV} && "
            f"{PERCCLI} /c0/eall/sall show all 2>/dev/null"
        )
        out = await _ssh_run(host, ssh_user, ssh_password, perccli_cmd, timeout=30)
        if "Status = Failure" in out or "Drive Information" in out or "Onln" in out or "UGood" in out:
            pd_data = _parse_perccli_pd(out)
            metrics_data.update(pd_data)
            inventory_data.update({k: v for k, v in pd_data.items()
                                    if any(x in k for x in
                                           [".model", ".serial", ".firmware", ".interface", ".media"])})

        # ── Virtual Drives via perccli ────────────────────────────────────────
        vd_cmd = f"{PERCCLI_ENV} && {PERCCLI} /c0/vall show 2>/dev/null"
        out = await _ssh_run(host, ssh_user, ssh_password, vd_cmd, timeout=20)
        vd_data = _parse_perccli_vd(out)
        metrics_data.update(vd_data)
        inventory_data.update({k: v for k, v in vd_data.items()
                                if ".raid_level" in k})

        log.info(
            f"[esxi_ssh] {device_id}: collected "
            f"{len(metrics_data)} metrics, {len(inventory_data)} inventory keys"
        )

        # ── Publish metrics ───────────────────────────────────────────────────
        if metrics_data:
            env = _build_envelope("metrics", device_id, agent_id, tenant_id, metrics_data)
            mqtt_client.publish("metrics.slow", env)

        # ── Publish inventory ─────────────────────────────────────────────────
        if inventory_data:
            env = _build_envelope("inventory", device_id, agent_id, tenant_id, inventory_data)
            mqtt_client.publish("inventory", env)

    except TimeoutError as e:
        log.warning(f"[esxi_ssh] {device_id}: {e}")
    except Exception as e:
        log.error(f"[esxi_ssh] {device_id}: collection error: {e}", exc_info=True)


# ── Polling loop ────────────────────────────────────────────────────────────────


async def run_esxi_poller(mqtt_client, config) -> None:
    """
    Background task: polls all devices with collector_type='esxi_ssh'.
    Re-runs every poll_interval_slow seconds (default 300).

    Device must have:
      collector_type = 'esxi_ssh'
      ip            = ESXi management IP
      snmp_community = SSH password (reused field)
      snmp_v3_user   = SSH username (default: root)
    """
    from core.database import get_session, Device
    import sqlmodel

    agent_id = getattr(config.server, "agent_id", "") or ""
    tenant_id = getattr(config.server, "tenant_id", "") or ""

    log.info("[esxi_ssh] ESXi SSH poller started")

    while True:
        try:
            with get_session() as s:
                devices = s.exec(
                    __import__("sqlmodel").select(Device).where(
                        Device.collector_type == "esxi_ssh",
                        Device.status == "active",
                    )
                ).all()

            if not devices:
                await asyncio.sleep(60)
                continue

            for dev in devices:
                ssh_user = dev.snmp_v3_user or "root"
                ssh_pass = dev.snmp_community or ""
                if not ssh_pass:
                    log.warning(f"[esxi_ssh] {dev.device_id}: no SSH password (set snmp_community)")
                    continue

                await collect_esxi_device(
                    device_id=dev.device_id,
                    host=dev.ip,
                    ssh_user=ssh_user,
                    ssh_password=ssh_pass,
                    mqtt_client=mqtt_client,
                    agent_id=agent_id,
                    tenant_id=tenant_id,
                )

                interval = dev.poll_interval_slow or 300
                await asyncio.sleep(interval)

        except Exception as e:
            log.error(f"[esxi_ssh] poller loop error: {e}", exc_info=True)
            await asyncio.sleep(30)
