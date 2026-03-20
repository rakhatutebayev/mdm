"""Dell iDRAC device template."""
from __future__ import annotations

from typing import Any

from proxy_agent.templates.base import DeviceTemplate

# Коды RAID из Dell PERC / virtualDisk MIB (могут отличаться по прошивке)
RAID_TYPE_BY_CODE: dict[int, str] = {
    0: "Unknown",
    1: "RAID-0",
    2: "RAID-1",
    3: "RAID-5",
    4: "RAID-6",
    5: "RAID-1+0",
    6: "RAID-5+0",
    7: "RAID-6+0",
    8: "Concatenated",
}

DELL_STATUS_BY_CODE: dict[str, str] = {
    "1": "Other",
    "2": "Unknown",
    "3": "OK",
    "4": "Non-Critical",
    "5": "Critical",
    "6": "Non-Recoverable",
}


def _dell_snmp_status_label(code: str) -> str:
    text = str(code or "").strip()
    if not text:
        return "Unknown"
    return DELL_STATUS_BY_CODE.get(text, f"Code {text}")


def _component_status_from_code(code: str) -> str:
    text = str(code or "").strip()
    if text == "3":
        return "OK"
    if text in ("5", "6"):
        return "Critical"
    if text in ("1", "2", "4"):
        return "Warning"
    return "Unknown"


def _raid_type_label(code: str) -> str:
    text = str(code or "").strip()
    if not text:
        return ""
    try:
        return RAID_TYPE_BY_CODE.get(int(text), f"Code {text}")
    except ValueError:
        return text


# HOST-RESOURCES-MIB hrDeviceStatus
HR_DEVICE_STATUS_LABEL: dict[str, str] = {
    "1": "Unknown",
    "2": "Running",
    "3": "Warning",
    "4": "Testing",
    "5": "Down",
}


def _hr_device_health_label(code: str) -> str:
    text = str(code or "").strip()
    if not text:
        return "Unknown"
    return HR_DEVICE_STATUS_LABEL.get(text, f"Code {text}")


def _hr_component_status(code: str) -> str:
    text = str(code or "").strip()
    if text == "2":
        return "OK"
    if text == "3":
        return "Warning"
    if text in ("4", "5"):
        return "Critical"
    return "Unknown"


class DellIdracTemplate(DeviceTemplate):
    key = "dell_idrac"
    display_name = "Dell iDRAC"
    supported_protocols = ["snmp", "redfish"]

    def match(self, raw_facts: dict[str, Any]) -> bool:
        combined = " ".join(
            [
                str(raw_facts.get("sys_descr", "") or ""),
                str(raw_facts.get("sys_name", "") or ""),
                str(raw_facts.get("model", "") or ""),
            ]
        ).lower()
        return "idrac" in combined or "remote access controller" in combined

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        dell_details = raw_facts.get("dell_details")
        if not isinstance(dell_details, dict):
            dell_details = {}

        model = (
            str(dell_details.get("controller_model", "") or "").strip()
            or str(raw_facts.get("model", "") or "").strip()
            or "iDRAC"
        )
        display_name = (
            str(raw_facts.get("sys_name", "") or "").strip()
            or f"Dell {model}"
        )
        service_tag = str(dell_details.get("service_tag", "") or raw_facts.get("serial_number", "") or "").strip()
        firmware = str(dell_details.get("controller_firmware", "") or raw_facts.get("firmware_version", "") or "").strip()
        management_url = str(dell_details.get("management_url", "") or "").strip()
        global_status_code = str(dell_details.get("global_status", "") or "").strip()
        global_status = {
            "1": "Other",
            "2": "Unknown",
            "3": "OK",
            "4": "Non-Critical",
            "5": "Critical",
            "6": "Non-Recoverable",
        }.get(global_status_code, global_status_code)

        storage = raw_facts.get("dell_storage")
        if not isinstance(storage, dict):
            storage = {}
        storage_pds: list[dict[str, Any]] = list(storage.get("physical_disks") or [])
        storage_vds: list[dict[str, Any]] = list(storage.get("virtual_disks") or [])
        storage_ctls: list[dict[str, Any]] = list(storage.get("controllers") or [])
        hr_hints: list[dict[str, Any]] = [h for h in (storage.get("host_resource_hints") or []) if isinstance(h, dict)]
        has_storage_mib = bool(storage_pds or storage_vds or storage_ctls)
        # Когда Dell Storage MIB пуст (iDRAC6), показываем LUN/PERC из hrDevice
        show_hr_storage = bool(hr_hints) and not storage_pds and not storage_vds

        raid_labels = sorted(
            {
                _raid_type_label(str(row.get("raid_type_code", "") or ""))
                for row in storage_vds
                if isinstance(row, dict) and str(row.get("raid_type_code", "") or "").strip()
            }
        )
        raid_summary = ", ".join(raid_labels) if raid_labels else None
        if not raid_summary and has_storage_mib:
            raid_summary = "Dell Storage MIB (no RAID type OIDs)"
        if show_hr_storage and not has_storage_mib:
            raid_summary = "Host Resources MIB hints (limited; no Dell Storage tables)"

        inventory = {
            "processor_model": "",
            "processor_vendor": "",
            "processor_count": None,
            "physical_cores": None,
            "logical_processors": None,
            "memory_total_gb": None,
            "memory_slot_count": None,
            "memory_slots_used": None,
            "memory_module_count": None,
            "storage_controller_count": len(storage_ctls) if has_storage_mib else None,
            "physical_disk_count": (len(storage_pds) if has_storage_mib else (len(hr_hints) if show_hr_storage else None)),
            "virtual_disk_count": len(storage_vds) if has_storage_mib else None,
            "disk_total_gb": None,
            "network_interface_count": None,
            "power_supply_count": None,
            "raid_summary": raid_summary
            if (has_storage_mib or show_hr_storage)
            else "Legacy iDRAC6 SNMP profile exposes limited hardware details",
        }

        worst_storage = "OK"
        for row in storage_ctls + storage_pds + storage_vds:
            if not isinstance(row, dict):
                continue
            st = _component_status_from_code(str(row.get("status_code", "") or ""))
            if st == "Critical":
                worst_storage = "Critical"
            elif st == "Warning" and worst_storage == "OK":
                worst_storage = "Warning"
        for row in hr_hints:
            st = _hr_component_status(str(row.get("status_code", "") or ""))
            if st == "Critical":
                worst_storage = "Critical"
            elif st == "Warning" and worst_storage == "OK":
                worst_storage = "Warning"

        health = {
            "overall_status": global_status or "Unknown",
            "processor_status": "",
            "memory_status": "",
            "storage_status": worst_storage if (has_storage_mib or hr_hints) else "",
            "power_status": "",
            "network_status": "",
            "thermal_status": "",
            "power_state": "",
            "alert_count": 1 if global_status in {"Critical", "Non-Recoverable", "Non-Critical"} else 0,
            "summary": "",
        }
        if has_storage_mib:
            health["summary"] = (
                f"iDRAC SNMP: {global_status or 'Unknown'}; "
                f"storage MIB: {len(storage_ctls)} controller(s), {len(storage_pds)} physical disk(s), "
                f"{len(storage_vds)} virtual disk(s)."
            )
        elif show_hr_storage:
            health["summary"] = (
                f"iDRAC SNMP: {global_status or 'Unknown'}; "
                f"Host Resources: {len(hr_hints)} storage-related device(s) (no Dell Storage MIB rows)."
            )
        else:
            health["summary"] = f"Legacy Dell SNMP overall status: {global_status or 'Unknown'}"

        components: list[dict[str, Any]] = [
            {
                "component_type": "management_controller",
                "name": str(dell_details.get("controller_name", "") or "Integrated Dell Remote Access Controller"),
                "slot": "",
                "model": model,
                "manufacturer": str(dell_details.get("controller_vendor", "") or "Dell"),
                "serial_number": service_tag,
                "firmware_version": firmware,
                "capacity_gb": None,
                "status": global_status or "Unknown",
                "health": global_status or "Unknown",
                "extra_json": {
                    "management_url": management_url,
                    "status_code": global_status_code,
                },
            }
        ]

        for row in storage_ctls:
            if not isinstance(row, dict):
                continue
            idx = str(row.get("index", "") or "").strip()
            code = str(row.get("status_code", "") or "").strip()
            components.append(
                {
                    "component_type": "raid_controller",
                    "name": str(row.get("model", "") or "").strip() or f"RAID controller {idx}",
                    "slot": "",
                    "model": str(row.get("model", "") or "").strip(),
                    "manufacturer": "Dell",
                    "serial_number": "",
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "snmp_index": idx,
                        "status_code": code,
                        "source": "idrac_dell_storage_mib",
                    },
                }
            )

        for row in storage_pds:
            if not isinstance(row, dict):
                continue
            idx = str(row.get("index", "") or "").strip()
            code = str(row.get("status_code", "") or "").strip()
            model = str(row.get("model", "") or "").strip()
            serial = str(row.get("serial_number", "") or "").strip()
            size_raw = str(row.get("size_raw", "") or "").strip()
            components.append(
                {
                    "component_type": "physical_disk",
                    "name": model or f"Physical disk {idx}",
                    "slot": idx.replace(".", ":") if idx else "",
                    "model": model,
                    "manufacturer": "",
                    "serial_number": serial,
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "snmp_index": idx,
                        "status_code": code,
                        "size_raw": size_raw,
                        "source": "idrac_dell_storage_mib",
                    },
                }
            )

        for row in storage_vds:
            if not isinstance(row, dict):
                continue
            idx = str(row.get("index", "") or "").strip()
            code = str(row.get("status_code", "") or "").strip()
            size_raw = str(row.get("size_raw", "") or "").strip()
            raid_code = str(row.get("raid_type_code", "") or "").strip()
            raid_label = _raid_type_label(raid_code)
            components.append(
                {
                    "component_type": "virtual_disk",
                    "name": f"Virtual disk {idx}" + (f" ({raid_label})" if raid_label else ""),
                    "slot": "",
                    "model": raid_label or "",
                    "manufacturer": "",
                    "serial_number": "",
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "snmp_index": idx,
                        "status_code": code,
                        "raid_type_code": raid_code,
                        "raid_type": raid_label,
                        "size_raw": size_raw,
                        "source": "idrac_dell_storage_mib",
                    },
                }
            )

        if show_hr_storage:
            for row in hr_hints:
                idx = str(row.get("index", "") or "").strip()
                descr = str(row.get("description", "") or "").strip()
                code = str(row.get("status_code", "") or "").strip()
                if not descr:
                    continue
                components.append(
                    {
                        "component_type": "storage_device",
                        "name": descr[:240] + ("…" if len(descr) > 240 else ""),
                        "slot": idx,
                        "model": "",
                        "manufacturer": "",
                        "serial_number": "",
                        "firmware_version": "",
                        "capacity_gb": None,
                        "status": _hr_component_status(code),
                        "health": _hr_device_health_label(code),
                        "extra_json": {
                            "snmp_index": idx,
                            "hr_device_status": code,
                            "type_oid": row.get("type_oid", ""),
                            "source": "idrac_host_resources_mib",
                        },
                    }
                )

        alerts = []
        if global_status in {"Critical", "Non-Recoverable", "Non-Critical"}:
            alerts.append(
                {
                    "source": "legacy_idrac_snmp",
                    "severity": global_status.lower(),
                    "code": f"idrac_status_{global_status_code or 'unknown'}",
                    "message": f"Legacy iDRAC overall status is {global_status}",
                    "status": "active",
                    "first_seen_at": None,
                    "last_seen_at": None,
                    "cleared_at": None,
                    "extra_json": {
                        "management_url": management_url,
                    },
                }
            )

        return {
            "asset_class": "idrac",
            "display_name": display_name,
            "vendor": "Dell",
            "model": model,
            "serial_number": service_tag,
            "firmware_version": firmware,
            "ip_address": str(raw_facts.get("ip_address", "") or ""),
            "management_ip": str(raw_facts.get("management_ip", "") or ""),
            "mac_address": str(raw_facts.get("mac_address", "") or ""),
            "status": global_status or "Discovered",
            "inventory": inventory,
            "components": components,
            "health": health,
            "alerts": alerts,
            "raw_facts": self.build_raw_facts(
                raw_facts,
                {
                    "vendor": "Dell",
                    "management_url": management_url,
                    "global_status": global_status,
                    "global_status_code": global_status_code,
                    "storage_via_snmp": bool(has_storage_mib),
                    "storage_via_hr_hints": bool(show_hr_storage),
                },
            ),
        }
