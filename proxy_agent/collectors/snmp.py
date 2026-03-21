"""Raw SNMP transport collector for Proxy Agent."""
from __future__ import annotations

import ipaddress
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import paramiko

from proxy_agent.collectors.esxi_perccli import collect_esxi_perccli

try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
        nextCmd,
    )
except Exception as exc:  # pragma: no cover - runtime dependency guard
    raise RuntimeError(
        "Missing dependency: pysnmp. Install with `python3 -m pip install pysnmp`."
    ) from exc


BASE_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
}

ENTITY_MODEL_SUBTREE = "1.3.6.1.2.1.47.1.1.1.1.13"
ENTITY_SERIAL_SUBTREE = "1.3.6.1.2.1.47.1.1.1.1.11"
ENTITY_FW_SUBTREE = "1.3.6.1.2.1.47.1.1.1.1.10"
IF_DESCR_SUBTREE = "1.3.6.1.2.1.2.2.1.2"
IF_PHYS_ADDRESS_1 = "1.3.6.1.2.1.2.2.1.6.1"
IF_PHYS_ADDRESS_SUBTREE = "1.3.6.1.2.1.2.2.1.6"
HR_STORAGE_TYPE_SUBTREE = "1.3.6.1.2.1.25.2.3.1.2"
HR_STORAGE_DESC_SUBTREE = "1.3.6.1.2.1.25.2.3.1.3"
HR_STORAGE_ALLOC_UNITS_SUBTREE = "1.3.6.1.2.1.25.2.3.1.4"
HR_STORAGE_SIZE_SUBTREE = "1.3.6.1.2.1.25.2.3.1.5"
HR_STORAGE_USED_SUBTREE = "1.3.6.1.2.1.25.2.3.1.6"
HR_DEVICE_TYPE_SUBTREE = "1.3.6.1.2.1.25.3.2.1.2"
HR_DEVICE_DESC_SUBTREE = "1.3.6.1.2.1.25.3.2.1.3"
HR_DEVICE_STATUS_SUBTREE = "1.3.6.1.2.1.25.3.2.1.5"
DELL_OIDS = {
    "controller_name": "1.3.6.1.4.1.674.10892.2.1.1.1.0",
    "controller_model": "1.3.6.1.4.1.674.10892.2.1.1.2.0",
    "controller_vendor": "1.3.6.1.4.1.674.10892.2.1.1.4.0",
    "controller_firmware": "1.3.6.1.4.1.674.10892.2.1.1.5.0",
    "management_url": "1.3.6.1.4.1.674.10892.2.1.1.7.0",
    "service_tag": "1.3.6.1.4.1.674.10892.2.1.1.11.0",
    "global_status": "1.3.6.1.4.1.674.10892.2.2.1.0",
    "system_model_name": "1.3.6.1.4.1.674.10892.5.1.3.12",
    "system_service_tag": "1.3.6.1.4.1.674.10892.5.1.3.2",
    "system_asset_tag": "1.3.6.1.4.1.674.10892.5.1.3.4",
}
DELL_STATUS_MAP = {
    "1": "Other",
    "2": "Unknown",
    "3": "OK",
    "4": "Non-Critical",
    "5": "Critical",
    "6": "Non-Recoverable",
}

# Dell iDRAC Storage / PERC SNMP (iDRAC 8/9+; iDRAC6 часто пусто)
DELL_STORAGE_PD_STATUS = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.4"
DELL_STORAGE_PD_MODEL = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.6"
DELL_STORAGE_PD_SERIAL = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.10"
DELL_STORAGE_PD_SIZE = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.11"
DELL_STORAGE_VD_STATUS = "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.4"
DELL_STORAGE_VD_SIZE = "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.6"
DELL_STORAGE_VD_RAID = "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.13"
DELL_STORAGE_CTL_STATUS = "1.3.6.1.4.1.674.10892.5.5.1.20.130.1.1.5"
DELL_STORAGE_CTL_MODEL = "1.3.6.1.4.1.674.10892.5.5.1.20.130.1.1.2"
DELL_STORAGE_WALK_MAX = 384

IDRAC_PROCESSOR_STATUS = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.5"
IDRAC_PROCESSOR_TYPE = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.7"
IDRAC_PROCESSOR_MANUFACTURER = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.8"
IDRAC_PROCESSOR_CURRENT_SPEED = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.12"
IDRAC_PROCESSOR_VERSION = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.16"
IDRAC_PROCESSOR_CORE_COUNT = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.17"
IDRAC_PROCESSOR_THREAD_COUNT = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.19"
IDRAC_PROCESSOR_BRAND = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.23"
IDRAC_PROCESSOR_FQDD = "1.3.6.1.4.1.674.10892.5.4.1100.30.1.26"

IDRAC_MEMORY_STATUS = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.5"
IDRAC_MEMORY_TYPE = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.7"
IDRAC_MEMORY_LOCATION = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.8"
IDRAC_MEMORY_BANK = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.10"
IDRAC_MEMORY_SIZE_KB = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.14"
IDRAC_MEMORY_SPEED_NS = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.15"
IDRAC_MEMORY_MANUFACTURER = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.21"
IDRAC_MEMORY_PART_NUMBER = "1.3.6.1.4.1.674.10892.5.4.1100.50.1.22"

IDRAC_POWER_STATUS = "1.3.6.1.4.1.674.10892.5.4.600.12.1.5"
IDRAC_POWER_OUTPUT_WATTS_TENTHS = "1.3.6.1.4.1.674.10892.5.4.600.12.1.6"
IDRAC_POWER_TYPE = "1.3.6.1.4.1.674.10892.5.4.600.12.1.7"
IDRAC_POWER_LOCATION = "1.3.6.1.4.1.674.10892.5.4.600.12.1.8"
IDRAC_POWER_INPUT_VOLTAGE = "1.3.6.1.4.1.674.10892.5.4.600.12.1.9"
IDRAC_POWER_SENSOR_STATE = "1.3.6.1.4.1.674.10892.5.4.600.12.1.11"
IDRAC_POWER_FQDD = "1.3.6.1.4.1.674.10892.5.4.600.12.1.15"

IDRAC_COOLING_STATUS = "1.3.6.1.4.1.674.10892.5.4.700.12.1.5"
IDRAC_COOLING_READING = "1.3.6.1.4.1.674.10892.5.4.700.12.1.6"
IDRAC_COOLING_TYPE = "1.3.6.1.4.1.674.10892.5.4.700.12.1.7"
IDRAC_COOLING_LOCATION = "1.3.6.1.4.1.674.10892.5.4.700.12.1.8"

IDRAC_TEMPERATURE_STATUS = "1.3.6.1.4.1.674.10892.5.4.700.20.1.5"
IDRAC_TEMPERATURE_READING = "1.3.6.1.4.1.674.10892.5.4.700.20.1.6"
IDRAC_TEMPERATURE_TYPE = "1.3.6.1.4.1.674.10892.5.4.700.20.1.7"
IDRAC_TEMPERATURE_LOCATION = "1.3.6.1.4.1.674.10892.5.4.700.20.1.8"

IDRAC_COMPONENT_WALK_MAX = 256


def _storage_walk_target(base: SnmpTarget) -> SnmpTarget:
    """Более длинный timeout/retries для таблиц iDRAC (иначе пустые ответы при 0.8s)."""
    if base.storage_timeout_s is not None and float(base.storage_timeout_s) > 0:
        timeout_s = float(base.storage_timeout_s)
    else:
        timeout_s = max(3.0, float(base.timeout_s) * 4.0)
    retries = max(1, int(base.retries))
    return replace(base, timeout_s=timeout_s, retries=retries)


def _collect_idrac_host_resource_hints(ip: str, target: SnmpTarget) -> list[dict[str, str]]:
    """
    Если Dell Storage MIB пуст (часто iDRAC6), часть LUN/дисков видна в Host Resources hrDeviceTable.
    """
    device_type = _snmp_walk_subtree(ip, HR_DEVICE_TYPE_SUBTREE, target, DELL_STORAGE_WALK_MAX)
    device_desc = _snmp_walk_subtree(ip, HR_DEVICE_DESC_SUBTREE, target, DELL_STORAGE_WALK_MAX)
    device_status = _snmp_walk_subtree(ip, HR_DEVICE_STATUS_SUBTREE, target, DELL_STORAGE_WALK_MAX)
    keywords = (
        "lun",
        "perc",
        "raid",
        "virtual disk",
        "physical disk",
        "physicaldrive",
        "vd ",
        "disk ",
        "megaraid",
        "sas ",
        "sata ",
        "naa.",
    )
    hints: list[dict[str, str]] = []
    for idx, descr in device_desc.items():
        dlow = descr.lower()
        if not any(k in dlow for k in keywords):
            continue
        hints.append(
            {
                "index": idx,
                "description": descr,
                "type_oid": device_type.get(idx, ""),
                "status_code": device_status.get(idx, ""),
            }
        )
    return hints
AVAYA_1600_OIDS = {
    "mac_address": "1.3.6.1.4.1.6889.2.69.3.1.42.0",
    "model": "1.3.6.1.4.1.6889.2.69.3.1.43.0",
    "phone_number": "1.3.6.1.4.1.6889.2.69.3.1.45.0",
    "extension": "1.3.6.1.4.1.6889.2.69.3.6.3.0",
    "serial_number": "1.3.6.1.4.1.6889.2.69.3.1.46.0",
    "firmware_version": "1.3.6.1.4.1.6889.2.69.3.1.58.0",
    "serial_number_alt": "1.3.6.1.4.1.6889.2.69.3.1.59.0",
}
VMWARE_OIDS = {
    "product_version": "1.3.6.1.4.1.6876.3.1.1.0",
    "memory_total_kb": "1.3.6.1.4.1.6876.3.2.1.0",
    "memory_used_kb": "1.3.6.1.4.1.6876.3.2.2.0",
    "memory_free_kb": "1.3.6.1.4.1.6876.3.2.3.0",
}
VMWARE_HBA_COUNT = "1.3.6.1.4.1.6876.3.5.1.0"
VMWARE_HBA_NAME_SUBTREE = "1.3.6.1.4.1.6876.3.5.2.1.2"
VMWARE_HBA_STATUS_SUBTREE = "1.3.6.1.4.1.6876.3.5.2.1.3"
VMWARE_HBA_MODEL_SUBTREE = "1.3.6.1.4.1.6876.3.5.2.1.5"
VMWARE_HBA_DRIVER_SUBTREE = "1.3.6.1.4.1.6876.3.5.2.1.6"
VMWARE_HBA_PCI_SUBTREE = "1.3.6.1.4.1.6876.3.5.2.1.7"


@dataclass
class SnmpTarget:
    name: str
    community: str
    port: int = 161
    timeout_s: float = 0.8
    retries: int = 0
    hosts: list[str] | None = None
    subnet: str | None = None
    workers: int = 32
    template_key: str = ""
    only_match: str = ""
    ssh_username: str = ""
    ssh_password: str = ""
    ssh_port: int = 22
    perccli_path: str = "/opt/lsi/perccli/perccli"
    perccli_controller: int = 0
    # iDRAC: Dell Storage MIB + Host Resources hints (медленные walk — отдельный таймаут)
    idrac_storage_enabled: bool = True
    storage_timeout_s: float | None = None


def _safe_str(value: Any) -> str:
    if hasattr(value, "asOctets"):
        try:
            raw = bytes(value.asOctets())
            if raw:
                cleaned = raw.rstrip(b"\x00")
                if cleaned and all(32 <= byte <= 126 for byte in cleaned):
                    return cleaned.decode("utf-8", errors="ignore").strip()
                return ":".join(f"{byte:02X}" for byte in raw)
        except Exception:
            pass
    text = str(value or "").strip()
    if text.startswith("0x"):
        try:
            raw = bytes.fromhex(text[2:])
            return ":".join(f"{byte:02X}" for byte in raw)
        except Exception:
            return text
    return text.replace("\x00", "")


def _snmp_get(ip: str, oid: str, target: SnmpTarget) -> str:
    iterator = getCmd(
        SnmpEngine(),
        CommunityData(target.community, mpModel=1),
        UdpTransportTarget((ip, target.port), timeout=target.timeout_s, retries=target.retries),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    error_indication, error_status, _error_index, var_binds = next(iterator)
    if error_indication or error_status:
        return ""
    for _name, value in var_binds:
        return _safe_str(value)
    return ""


def _snmp_first_subtree_value(ip: str, subtree_oid: str, target: SnmpTarget, max_rows: int = 20) -> str:
    count = 0
    for error_indication, error_status, _error_index, var_binds in nextCmd(
        SnmpEngine(),
        CommunityData(target.community, mpModel=1),
        UdpTransportTarget((ip, target.port), timeout=target.timeout_s, retries=target.retries),
        ContextData(),
        ObjectType(ObjectIdentity(subtree_oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            return ""
        for _name, value in var_binds:
            text = _safe_str(value)
            if text:
                return text
        count += 1
        if count >= max_rows:
            break
    return ""


def _snmp_walk_subtree(ip: str, subtree_oid: str, target: SnmpTarget, max_rows: int = 128) -> dict[str, str]:
    rows: dict[str, str] = {}
    count = 0
    prefix = f"{subtree_oid}."
    for error_indication, error_status, _error_index, var_binds in nextCmd(
        SnmpEngine(),
        CommunityData(target.community, mpModel=1),
        UdpTransportTarget((ip, target.port), timeout=target.timeout_s, retries=target.retries),
        ContextData(),
        ObjectType(ObjectIdentity(subtree_oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            return rows
        for name, value in var_binds:
            oid = str(name)
            if not oid.startswith(prefix):
                return rows
            suffix = oid[len(prefix):].strip(".")
            rows[suffix] = _safe_str(value)
            count += 1
            if count >= max_rows:
                return rows
    return rows


RACADM_SEL_TIME_FORMATS = (
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%y %H:%M:%S",
    "%a %b %d %H:%M:%S %Y",
    "%b %d %H:%M:%S %Y",
    "%b %d %Y %H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
)


def _parse_racadm_timestamp(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    if not text:
        return ""
    for fmt in RACADM_SEL_TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt).isoformat(sep=" ")
        except ValueError:
            continue
    return text


def _event_sort_key(entry: dict[str, Any]) -> tuple[int, str]:
    event_time = str(entry.get("event_time", "") or "").strip()
    record_id = str(entry.get("record_id", "") or "").strip()
    try:
        record_rank = int(record_id)
    except ValueError:
        record_rank = -1
    return (record_rank, event_time)


def _normalize_alert_severity(value: Any) -> str:
    text = str(value or "").strip().lower()
    if text in {"critical", "non-recoverable", "fatal"}:
        return "critical"
    if text in {"warning", "non-critical", "warn"}:
        return "warning"
    if text in {"informational", "info"}:
        return "info"
    if text in {"ok", "normal"}:
        return "ok"
    return text or "unknown"


def _parse_racadm_sel_entries(text: str) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        if re.match(r"^(?:Record|SEL Record(?: ID)?)\b", line, re.IGNORECASE) and current:
            blocks.append(current)
            current = [line]
            continue
        current.append(line)
    if current:
        blocks.append(current)

    for block in blocks:
        entry: dict[str, str] = {}
        free_text: list[str] = []
        for line in block:
            record_match = re.match(r"^(?:Record|SEL Record(?: ID)?)\s*[:#]?\s*([0-9]+)\b", line, re.IGNORECASE)
            if record_match:
                entry["record_id"] = record_match.group(1)
                continue

            key_match = re.match(r"^([^:=]+?)\s*[:=]\s*(.+)$", line)
            if key_match:
                raw_key = key_match.group(1).strip().lower()
                value = key_match.group(2).strip()
                if raw_key in {"date/time", "datetime", "date and time", "timestamp", "time", "event time"}:
                    entry["event_time"] = _parse_racadm_timestamp(value)
                    entry["event_time_raw"] = value
                    continue
                if raw_key in {"severity", "event severity"}:
                    entry["severity"] = value
                    continue
                if raw_key in {"description", "message", "event description", "event message", "text"}:
                    entry["message"] = value
                    continue
                if raw_key in {"category", "sensor", "generator id"}:
                    entry[raw_key.replace(" ", "_")] = value
                    continue

            inline_match = re.search(
                r"(?P<record>Record\s*[0-9]+).*?(?P<time>\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}:\d{2}).*?"
                r"(?P<severity>Critical|Warning|Non-Critical|Non-Recoverable|Informational|Info)\b.*?(?P<message>.+)$",
                line,
                re.IGNORECASE,
            )
            if inline_match:
                entry["record_id"] = re.sub(r"\D+", "", inline_match.group("record"))
                entry["event_time"] = _parse_racadm_timestamp(inline_match.group("time"))
                entry["event_time_raw"] = inline_match.group("time")
                entry["severity"] = inline_match.group("severity")
                entry["message"] = inline_match.group("message").strip(" -")
                continue

            free_text.append(line)

        if not entry.get("message") and free_text:
            entry["message"] = free_text[-1]
        if entry.get("message"):
            entries.append(entry)

    entries.sort(key=_event_sort_key, reverse=True)
    return entries


def _run_ssh_command(
    host: str,
    username: str,
    password: str,
    port: int,
    command: str,
    timeout_s: float,
) -> tuple[int, str, str]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout_s,
        banner_timeout=timeout_s,
        auth_timeout=timeout_s,
    )
    try:
        stdin, stdout, stderr = client.exec_command(command, timeout=timeout_s)
        _ = stdin
        out = stdout.read().decode("utf-8", errors="ignore")
        err = stderr.read().decode("utf-8", errors="ignore")
        code = stdout.channel.recv_exit_status()
        return code, out, err
    finally:
        client.close()


def _run_ssh_commands(
    host: str,
    username: str,
    password: str,
    port: int,
    commands: list[str],
    timeout_s: float,
) -> dict[str, tuple[int, str, str]]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout_s,
        banner_timeout=timeout_s,
        auth_timeout=timeout_s,
    )
    try:
        results: dict[str, tuple[int, str, str]] = {}
        for command in commands:
            stdin, stdout, stderr = client.exec_command(command, timeout=timeout_s)
            _ = stdin
            out = stdout.read().decode("utf-8", errors="ignore")
            err = stderr.read().decode("utf-8", errors="ignore")
            code = stdout.channel.recv_exit_status()
            results[command] = (code, out, err)
        return results
    finally:
        client.close()


def _snake_case_label(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    return text.strip("_")


def _parse_racadm_equals_lines(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            line = line[1:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[_snake_case_label(key)] = value.strip()
    return values


def _parse_racadm_getsysinfo(text: str) -> dict[str, Any]:
    sections: dict[str, dict[str, str]] = {}
    current_section = "root"
    sections[current_section] = {}
    embedded_nics: list[dict[str, str]] = []
    current_embedded_base = ""
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.endswith(":") and "=" not in stripped:
            current_section = _snake_case_label(stripped[:-1]) or "root"
            sections.setdefault(current_section, {})
            current_embedded_base = ""
            continue
        if "=" not in stripped:
            continue
        key, value = [part.strip() for part in stripped.split("=", 1)]
        if current_section == "embedded_nic_mac_addresses":
            if raw_line[:1].isspace():
                nic_name = f"{current_embedded_base} {key}".strip()
            else:
                nic_name = key
                current_embedded_base = key.split()[0]
            embedded_nics.append(
                {
                    "name": nic_name,
                    "mac_address": value.upper(),
                }
            )
            continue
        sections.setdefault(current_section, {})[_snake_case_label(key)] = value
    return {
        "sections": sections,
        "embedded_nics": embedded_nics,
    }


def _collect_idrac_racadm_details(host: str, target: SnmpTarget) -> dict[str, Any]:
    commands = [
        "racadm getsysinfo",
        "racadm getversion",
        "racadm getniccfg",
        "racadm getconfig -g cfgServerPower",
        "racadm getconfig -g cfgLanNetworking",
        "racadm getconfig -g ifcRacManagedNodeOs",
        "racadm getconfig -g cfgSensorRedundancy -i 1",
    ]
    commands.extend(f"racadm getconfig -g cfgServerPowerSupply -i {index}" for index in range(1, 5))
    results = _run_ssh_commands(
        host=host,
        username=target.ssh_username,
        password=target.ssh_password,
        port=target.ssh_port,
        commands=commands,
        timeout_s=max(10.0, target.timeout_s * 12),
    )
    getsysinfo = _parse_racadm_getsysinfo(results["racadm getsysinfo"][1])
    getversion = _parse_racadm_equals_lines(results["racadm getversion"][1])
    getniccfg = _parse_racadm_getsysinfo(results["racadm getniccfg"][1])
    server_power = _parse_racadm_equals_lines(results["racadm getconfig -g cfgServerPower"][1])
    lan_networking = _parse_racadm_equals_lines(results["racadm getconfig -g cfgLanNetworking"][1])
    managed_node_os = _parse_racadm_equals_lines(results["racadm getconfig -g ifcRacManagedNodeOs"][1])
    sensor_redundancy = _parse_racadm_equals_lines(results["racadm getconfig -g cfgSensorRedundancy -i 1"][1])
    power_supplies: list[dict[str, str]] = []
    for index in range(1, 5):
        command = f"racadm getconfig -g cfgServerPowerSupply -i {index}"
        parsed = _parse_racadm_equals_lines(results[command][1])
        if not parsed:
            continue
        parsed["index"] = str(index)
        if (
            parsed.get("cfgserverpowersupplyonlinestatus", "").strip().lower() == "absent"
            and parsed.get("cfgserverpowersupplymaxinputpower", "").strip().startswith("0 ")
            and parsed.get("cfgserverpowersupplymaxoutputpower", "").strip().startswith("0 ")
        ):
            continue
        power_supplies.append(parsed)
    errors = {
        command: err.strip()
        for command, (_, _, err) in results.items()
        if err.strip()
    }
    return {
        "getsysinfo": getsysinfo,
        "getversion": getversion,
        "getniccfg": getniccfg,
        "server_power": server_power,
        "lan_networking": lan_networking,
        "managed_node_os": managed_node_os,
        "sensor_redundancy": sensor_redundancy,
        "power_supplies": power_supplies,
        "errors": errors,
    }


def _collect_idrac_racadm_sel(host: str, target: SnmpTarget) -> dict[str, Any]:
    code, out, err = _run_ssh_command(
        host=host,
        username=target.ssh_username,
        password=target.ssh_password,
        port=target.ssh_port,
        command="racadm getsel -o",
        timeout_s=max(10.0, target.timeout_s * 10),
    )
    entries = _parse_racadm_sel_entries(out)
    latest_problem = next(
        (
            entry
            for entry in entries
            if _normalize_alert_severity(entry.get("severity")) in {"critical", "warning", "non-critical", "non-recoverable"}
        ),
        entries[0] if entries else {},
    )
    return {
        "command": "racadm getsel -o",
        "exit_code": code,
        "stderr": err.strip(),
        "entries": entries[:100],
        "exact_error": str(latest_problem.get("message", "") or "").strip(),
        "exact_severity": str(latest_problem.get("severity", "") or "").strip(),
        "exact_timestamp": str(latest_problem.get("event_time", "") or "").strip(),
    }


def _neighbor_mac(ip: str) -> str:
    try:
        result = subprocess.run(
            ["ip", "neigh", "show", ip],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    match = re.search(r"\blladdr\s+(([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})\b", result.stdout)
    if not match:
        return ""
    return match.group(1).upper()


def expand_targets(subnet: str | None, hosts: list[str] | None) -> list[str]:
    targets: list[str] = []
    if subnet:
        network = ipaddress.ip_network(subnet, strict=False)
        targets.extend(str(host) for host in network.hosts())
    for item in hosts or []:
        token = (item or "").strip()
        if token:
            ipaddress.ip_address(token)
            targets.append(token)
    return sorted(set(targets), key=lambda value: tuple(int(chunk) for chunk in value.split(".")))


def _storage_index_sort_key(suffix: str) -> tuple[int, ...]:
    parts: list[int] = []
    for part in suffix.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def _merge_storage_table(columns: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    suffixes: set[str] = set()
    for col in columns.values():
        suffixes.update(col.keys())
    rows: list[dict[str, str]] = []
    for suffix in sorted(suffixes, key=_storage_index_sort_key):
        row: dict[str, str] = {"index": suffix}
        for name, col in columns.items():
            row[name] = col.get(suffix, "")
        rows.append(row)
    return rows


def _collect_idrac_component_tables(ip: str, target: SnmpTarget) -> dict[str, list[dict[str, str]]]:
    st = _storage_walk_target(target)
    tables: dict[str, dict[str, dict[str, str]]] = {
        "processors": {
            "status_code": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_STATUS, st, IDRAC_COMPONENT_WALK_MAX),
            "type_code": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_TYPE, st, IDRAC_COMPONENT_WALK_MAX),
            "manufacturer": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_MANUFACTURER, st, IDRAC_COMPONENT_WALK_MAX),
            "current_speed_mhz": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_CURRENT_SPEED, st, IDRAC_COMPONENT_WALK_MAX),
            "version": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_VERSION, st, IDRAC_COMPONENT_WALK_MAX),
            "core_count": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_CORE_COUNT, st, IDRAC_COMPONENT_WALK_MAX),
            "thread_count": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_THREAD_COUNT, st, IDRAC_COMPONENT_WALK_MAX),
            "brand_name": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_BRAND, st, IDRAC_COMPONENT_WALK_MAX),
            "fqdd": _snmp_walk_subtree(ip, IDRAC_PROCESSOR_FQDD, st, IDRAC_COMPONENT_WALK_MAX),
        },
        "memory_devices": {
            "status_code": _snmp_walk_subtree(ip, IDRAC_MEMORY_STATUS, st, IDRAC_COMPONENT_WALK_MAX),
            "type_code": _snmp_walk_subtree(ip, IDRAC_MEMORY_TYPE, st, IDRAC_COMPONENT_WALK_MAX),
            "location_name": _snmp_walk_subtree(ip, IDRAC_MEMORY_LOCATION, st, IDRAC_COMPONENT_WALK_MAX),
            "bank_location_name": _snmp_walk_subtree(ip, IDRAC_MEMORY_BANK, st, IDRAC_COMPONENT_WALK_MAX),
            "size_kb": _snmp_walk_subtree(ip, IDRAC_MEMORY_SIZE_KB, st, IDRAC_COMPONENT_WALK_MAX),
            "speed_ns": _snmp_walk_subtree(ip, IDRAC_MEMORY_SPEED_NS, st, IDRAC_COMPONENT_WALK_MAX),
            "manufacturer": _snmp_walk_subtree(ip, IDRAC_MEMORY_MANUFACTURER, st, IDRAC_COMPONENT_WALK_MAX),
            "part_number": _snmp_walk_subtree(ip, IDRAC_MEMORY_PART_NUMBER, st, IDRAC_COMPONENT_WALK_MAX),
        },
        "power_supplies": {
            "status_code": _snmp_walk_subtree(ip, IDRAC_POWER_STATUS, st, IDRAC_COMPONENT_WALK_MAX),
            "output_tenths_watts": _snmp_walk_subtree(ip, IDRAC_POWER_OUTPUT_WATTS_TENTHS, st, IDRAC_COMPONENT_WALK_MAX),
            "type_code": _snmp_walk_subtree(ip, IDRAC_POWER_TYPE, st, IDRAC_COMPONENT_WALK_MAX),
            "location_name": _snmp_walk_subtree(ip, IDRAC_POWER_LOCATION, st, IDRAC_COMPONENT_WALK_MAX),
            "input_voltage": _snmp_walk_subtree(ip, IDRAC_POWER_INPUT_VOLTAGE, st, IDRAC_COMPONENT_WALK_MAX),
            "sensor_state": _snmp_walk_subtree(ip, IDRAC_POWER_SENSOR_STATE, st, IDRAC_COMPONENT_WALK_MAX),
            "fqdd": _snmp_walk_subtree(ip, IDRAC_POWER_FQDD, st, IDRAC_COMPONENT_WALK_MAX),
        },
        "cooling_devices": {
            "status_code": _snmp_walk_subtree(ip, IDRAC_COOLING_STATUS, st, IDRAC_COMPONENT_WALK_MAX),
            "reading_rpm": _snmp_walk_subtree(ip, IDRAC_COOLING_READING, st, IDRAC_COMPONENT_WALK_MAX),
            "type_code": _snmp_walk_subtree(ip, IDRAC_COOLING_TYPE, st, IDRAC_COMPONENT_WALK_MAX),
            "location_name": _snmp_walk_subtree(ip, IDRAC_COOLING_LOCATION, st, IDRAC_COMPONENT_WALK_MAX),
        },
        "temperature_probes": {
            "status_code": _snmp_walk_subtree(ip, IDRAC_TEMPERATURE_STATUS, st, IDRAC_COMPONENT_WALK_MAX),
            "reading_tenths_c": _snmp_walk_subtree(ip, IDRAC_TEMPERATURE_READING, st, IDRAC_COMPONENT_WALK_MAX),
            "type_code": _snmp_walk_subtree(ip, IDRAC_TEMPERATURE_TYPE, st, IDRAC_COMPONENT_WALK_MAX),
            "location_name": _snmp_walk_subtree(ip, IDRAC_TEMPERATURE_LOCATION, st, IDRAC_COMPONENT_WALK_MAX),
        },
    }

    out: dict[str, list[dict[str, str]]] = {}
    for key, columns in tables.items():
        rows = _merge_storage_table(columns)
        filtered: list[dict[str, str]] = []
        for row in rows:
            if any(str(value or "").strip() for field, value in row.items() if field != "index"):
                filtered.append(row)
        out[key] = filtered
    return out


def _collect_dell_idrac_storage(ip: str, target: SnmpTarget) -> dict[str, Any]:
    """
    Таблицы Dell Storage MIB по SNMP. На iDRAC6 обычно пусто — не ошибка.
    Дополнительно: host_resource_hints из hrDevice (LUN/PERC в описании).
    """
    st = _storage_walk_target(target)
    out: dict[str, Any] = {
        "physical_disks": [],
        "virtual_disks": [],
        "controllers": [],
        "host_resource_hints": [],
        "source": "dell_storage_mib_snmp",
        "walk_timeout_s": st.timeout_s,
    }
    try:
        pd_cols = {
            "status_code": _snmp_walk_subtree(ip, DELL_STORAGE_PD_STATUS, st, DELL_STORAGE_WALK_MAX),
            "model": _snmp_walk_subtree(ip, DELL_STORAGE_PD_MODEL, st, DELL_STORAGE_WALK_MAX),
            "serial_number": _snmp_walk_subtree(ip, DELL_STORAGE_PD_SERIAL, st, DELL_STORAGE_WALK_MAX),
            "size_raw": _snmp_walk_subtree(ip, DELL_STORAGE_PD_SIZE, st, DELL_STORAGE_WALK_MAX),
        }
        vd_cols = {
            "status_code": _snmp_walk_subtree(ip, DELL_STORAGE_VD_STATUS, st, DELL_STORAGE_WALK_MAX),
            "size_raw": _snmp_walk_subtree(ip, DELL_STORAGE_VD_SIZE, st, DELL_STORAGE_WALK_MAX),
            "raid_type_code": _snmp_walk_subtree(ip, DELL_STORAGE_VD_RAID, st, DELL_STORAGE_WALK_MAX),
        }
        ctl_cols = {
            "status_code": _snmp_walk_subtree(ip, DELL_STORAGE_CTL_STATUS, st, DELL_STORAGE_WALK_MAX),
            "model": _snmp_walk_subtree(ip, DELL_STORAGE_CTL_MODEL, st, DELL_STORAGE_WALK_MAX),
        }
    except Exception as exc:  # pragma: no cover - network
        out["error"] = str(exc)
        try:
            out["host_resource_hints"] = _collect_idrac_host_resource_hints(ip, st)
        except Exception:
            pass
        return out

    for row in _merge_storage_table(pd_cols):
        if not any(str(row.get(k, "")).strip() for k in ("status_code", "model", "serial_number", "size_raw")):
            continue
        out["physical_disks"].append(dict(row))

    for row in _merge_storage_table(vd_cols):
        if not any(str(row.get(k, "")).strip() for k in ("status_code", "size_raw", "raid_type_code")):
            continue
        out["virtual_disks"].append(dict(row))

    for row in _merge_storage_table(ctl_cols):
        if not any(str(row.get(k, "")).strip() for k in ("status_code", "model")):
            continue
        out["controllers"].append(dict(row))

    try:
        out["host_resource_hints"] = _collect_idrac_host_resource_hints(ip, st)
    except Exception as exc:  # pragma: no cover
        out["host_resource_hints_error"] = str(exc)

    return out


def probe_host(ip: str, target: SnmpTarget) -> dict[str, Any] | None:
    sys_descr = _snmp_get(ip, BASE_OIDS["sys_descr"], target)
    if not sys_descr:
        return None

    sys_name = _snmp_get(ip, BASE_OIDS["sys_name"], target)
    uptime = _snmp_get(ip, BASE_OIDS["sys_uptime"], target)
    model = _snmp_first_subtree_value(ip, ENTITY_MODEL_SUBTREE, target)
    serial = _snmp_first_subtree_value(ip, ENTITY_SERIAL_SUBTREE, target)
    firmware = _snmp_first_subtree_value(ip, ENTITY_FW_SUBTREE, target)
    mac = _snmp_get(ip, IF_PHYS_ADDRESS_1, target)
    dell_details: dict[str, str] = {}
    avaya_details: dict[str, str] = {}
    esxi_details: dict[str, Any] = {}
    dell_storage: dict[str, Any] = {}
    idrac_component_tables: dict[str, Any] = {}
    idrac_racadm_details: dict[str, Any] = {}

    if target.only_match:
        haystack = " ".join([sys_descr, sys_name, model]).lower()
        if target.only_match.strip().lower() not in haystack:
            return None

    haystack = " ".join([sys_descr, sys_name, model]).lower()
    if target.template_key == "dell_idrac" or "idrac" in haystack or "remote access controller" in haystack:
        for key, oid in DELL_OIDS.items():
            dell_details[key] = _snmp_get(ip, oid, target)
        try:
            idrac_component_tables = _collect_idrac_component_tables(ip, target)
        except Exception as exc:  # pragma: no cover
            idrac_component_tables = {
                "processors": [],
                "memory_devices": [],
                "power_supplies": [],
                "cooling_devices": [],
                "temperature_probes": [],
                "error": str(exc),
            }
        if target.idrac_storage_enabled:
            try:
                dell_storage = _collect_dell_idrac_storage(ip, target)
            except Exception as exc:  # pragma: no cover
                dell_storage = {
                    "error": str(exc),
                    "physical_disks": [],
                    "virtual_disks": [],
                    "controllers": [],
                    "host_resource_hints": [],
                }
        else:
            dell_storage = {
                "skipped": True,
                "physical_disks": [],
                "virtual_disks": [],
                "controllers": [],
                "host_resource_hints": [],
            }
        if target.ssh_username and target.ssh_password:
            try:
                idrac_racadm_details = _collect_idrac_racadm_details(ip, target)
                dell_details["racadm_details"] = idrac_racadm_details
            except Exception as exc:
                dell_details["racadm_details_error"] = str(exc)
                idrac_racadm_details = {"error": str(exc)}
            try:
                dell_details["racadm_sel"] = _collect_idrac_racadm_sel(ip, target)
            except Exception as exc:
                dell_details["racadm_sel_error"] = str(exc)

    if target.template_key == "avaya_1608" or ("avaya" in haystack and "1608" in haystack):
        for key, oid in AVAYA_1600_OIDS.items():
            avaya_details[key] = _snmp_get(ip, oid, target)
        model = model or avaya_details.get("model", "") or model
        serial = serial or avaya_details.get("serial_number", "") or avaya_details.get("serial_number_alt", "") or serial
        firmware = firmware or avaya_details.get("firmware_version", "") or firmware
        mac = mac or avaya_details.get("mac_address", "") or mac

    if target.template_key == "vmware_esxi" or "vmware esxi" in haystack:
        interfaces = []
        if_descr = _snmp_walk_subtree(ip, IF_DESCR_SUBTREE, target)
        if_mac = _snmp_walk_subtree(ip, IF_PHYS_ADDRESS_SUBTREE, target)
        for index, descr in if_descr.items():
            iface_mac = if_mac.get(index, "")
            interfaces.append(
                {
                    "index": index,
                    "name": descr,
                    "mac_address": iface_mac,
                }
            )
        vmk = next((item for item in interfaces if "vmk" in item["name"].lower() and item["mac_address"]), None)
        vmnic = next((item for item in interfaces if "vmnic" in item["name"].lower() and item["mac_address"]), None)
        mac = mac or (vmk or vmnic or {}).get("mac_address", "") or mac

        storage_type = _snmp_walk_subtree(ip, HR_STORAGE_TYPE_SUBTREE, target)
        storage_desc = _snmp_walk_subtree(ip, HR_STORAGE_DESC_SUBTREE, target)
        storage_alloc = _snmp_walk_subtree(ip, HR_STORAGE_ALLOC_UNITS_SUBTREE, target)
        storage_size = _snmp_walk_subtree(ip, HR_STORAGE_SIZE_SUBTREE, target)
        storage_used = _snmp_walk_subtree(ip, HR_STORAGE_USED_SUBTREE, target)
        storage_entries = []
        for index, descr in storage_desc.items():
            storage_entries.append(
                {
                    "index": index,
                    "type": storage_type.get(index, ""),
                    "description": descr,
                    "allocation_units": storage_alloc.get(index, ""),
                    "size": storage_size.get(index, ""),
                    "used": storage_used.get(index, ""),
                }
            )

        device_type = _snmp_walk_subtree(ip, HR_DEVICE_TYPE_SUBTREE, target)
        device_desc = _snmp_walk_subtree(ip, HR_DEVICE_DESC_SUBTREE, target)
        device_status = _snmp_walk_subtree(ip, HR_DEVICE_STATUS_SUBTREE, target)
        device_entries = []
        for index, descr in device_desc.items():
            device_entries.append(
                {
                    "index": index,
                    "type": device_type.get(index, ""),
                    "description": descr,
                    "status": device_status.get(index, ""),
                }
            )

        vmware_metrics = {key: _snmp_get(ip, oid, target) for key, oid in VMWARE_OIDS.items()}
        hba_name = _snmp_walk_subtree(ip, VMWARE_HBA_NAME_SUBTREE, target)
        hba_status = _snmp_walk_subtree(ip, VMWARE_HBA_STATUS_SUBTREE, target)
        hba_model = _snmp_walk_subtree(ip, VMWARE_HBA_MODEL_SUBTREE, target)
        hba_driver = _snmp_walk_subtree(ip, VMWARE_HBA_DRIVER_SUBTREE, target)
        hba_pci = _snmp_walk_subtree(ip, VMWARE_HBA_PCI_SUBTREE, target)
        hbas = []
        for index, name in hba_name.items():
            hbas.append(
                {
                    "index": index,
                    "name": name,
                    "status": hba_status.get(index, ""),
                    "model": hba_model.get(index, ""),
                    "driver": hba_driver.get(index, ""),
                    "pci": hba_pci.get(index, ""),
                }
            )
        esxi_details = {
            "interfaces": interfaces,
            "storage": storage_entries,
            "devices": device_entries,
            "vmware_metrics": vmware_metrics,
            "hbas": hbas,
            "hba_count": _snmp_get(ip, VMWARE_HBA_COUNT, target),
        }
        if target.ssh_username and target.ssh_password:
            try:
                esxi_details["perccli"] = collect_esxi_perccli(
                    host=ip,
                    username=target.ssh_username,
                    password=target.ssh_password,
                    perccli_path=target.perccli_path,
                    controller_index=target.perccli_controller,
                    timeout_s=max(10.0, target.timeout_s * 10),
                )
            except Exception as exc:
                esxi_details["perccli_error"] = str(exc)

    mac = mac or _neighbor_mac(ip)

    return {
        "protocol": "snmp",
        "target_name": target.name,
        "template_key": target.template_key,
        "ip_address": ip,
        "management_ip": ip,
        "sys_name": sys_name,
        "sys_descr": sys_descr,
        "uptime": uptime,
        "model": model,
        "serial_number": serial,
        "firmware_version": firmware,
        "mac_address": mac,
        "snmp_community": target.community,
        "dell_details": dell_details,
        "idrac_component_tables": idrac_component_tables,
        "idrac_racadm_details": idrac_racadm_details,
        "dell_storage": dell_storage,
        "avaya_details": avaya_details,
        "esxi_details": esxi_details,
    }


def collect_target(target: SnmpTarget) -> list[dict[str, Any]]:
    ips = expand_targets(target.subnet, target.hosts)
    if not ips:
        return []

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, target.workers)) as executor:
        futures = {executor.submit(probe_host, ip, target): ip for ip in ips}
        for future in as_completed(futures):
            result = future.result()
            if result:
                rows.append(result)

    rows.sort(key=lambda item: tuple(int(chunk) for chunk in item["management_ip"].split(".")))
    return rows
