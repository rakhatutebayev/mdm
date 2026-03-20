"""Raw SNMP transport collector for Proxy Agent."""
from __future__ import annotations

import ipaddress
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from typing import Any

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

    if target.only_match:
        haystack = " ".join([sys_descr, sys_name, model]).lower()
        if target.only_match.strip().lower() not in haystack:
            return None

    haystack = " ".join([sys_descr, sys_name, model]).lower()
    if target.template_key == "dell_idrac" or "idrac" in haystack or "remote access controller" in haystack:
        for key, oid in DELL_OIDS.items():
            dell_details[key] = _snmp_get(ip, oid, target)
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
