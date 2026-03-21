"""Dell iDRAC device template."""
from __future__ import annotations

import re
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

POWER_SUPPLY_TYPE_BY_CODE: dict[str, str] = {
    "1": "Other",
    "2": "Unknown",
    "3": "Linear",
    "4": "Switching",
    "5": "Battery",
    "6": "UPS",
    "7": "Converter",
    "8": "Regulator",
    "9": "AC",
    "10": "DC",
    "11": "VRM",
}

COOLING_TYPE_BY_CODE: dict[str, str] = {
    "1": "Other",
    "2": "Unknown",
    "3": "Fan",
    "4": "Blower",
    "5": "Chip Fan",
    "6": "Cabinet Fan",
    "7": "Power Supply Fan",
    "8": "Heat Pipe",
    "9": "Refrigeration",
    "10": "Active Cooling",
    "11": "Passive Cooling",
}

TEMPERATURE_TYPE_BY_CODE: dict[str, str] = {
    "1": "Other",
    "2": "Unknown",
    "3": "Ambient",
    "16": "Discrete",
}

MEMORY_TYPE_BY_CODE: dict[str, str] = {
    "1": "Other",
    "2": "Unknown",
    "3": "DRAM",
    "4": "EDRAM",
    "5": "VRAM",
    "6": "SRAM",
    "7": "RAM",
    "8": "ROM",
    "9": "FLASH",
    "10": "EEPROM",
    "11": "FEPROM",
    "12": "EPROM",
    "13": "CDRAM",
    "14": "3DRAM",
    "15": "SDRAM",
    "16": "SGRAM",
    "17": "RDRAM",
    "18": "DDR",
    "19": "DDR2",
    "20": "DDR2 FB-DIMM",
    "24": "DDR3",
    "25": "FBD2",
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


def _alert_severity(value: Any) -> str:
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


def _table_rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _safe_int(value: Any) -> int | None:
    try:
        return int(str(value or "").strip())
    except (TypeError, ValueError):
        return None


def _memory_size_gb(size_kb: Any) -> float | None:
    size = _safe_int(size_kb)
    if size is None or size <= 0 or size == 2147483647:
        return None
    return round(size / (1024 * 1024), 2)


def _power_watts(value: Any) -> float | None:
    watts_tenths = _safe_int(value)
    if watts_tenths is None:
        return None
    return round(watts_tenths / 10.0, 1)


def _temperature_c(value: Any) -> float | None:
    reading = _safe_int(value)
    if reading is None:
        return None
    return round(reading / 10.0, 1)


def _label_from_map(mapping: dict[str, str], code: Any) -> str:
    text = str(code or "").strip()
    return mapping.get(text, text)


def _obj(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _rows(value: Any) -> list[dict[str, Any]]:
    return [row for row in (value or []) if isinstance(row, dict)]


def _first_number(value: Any) -> float | None:
    match = re.search(r"-?\d+(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    number = float(match.group(0))
    return int(number) if number.is_integer() else number


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
        racadm_details = _obj(raw_facts.get("idrac_racadm_details") or dell_details.get("racadm_details"))
        racadm_system = _obj(racadm_details.get("getsysinfo"))
        racadm_system_sections = _obj(racadm_system.get("sections"))
        racadm_system_info = _obj(racadm_system_sections.get("system_information"))
        racadm_rac_info = _obj(racadm_system_sections.get("rac_information"))
        racadm_version = _obj(racadm_details.get("getversion"))
        racadm_power = _obj(racadm_details.get("server_power"))
        racadm_lan = _obj(racadm_details.get("lan_networking"))
        racadm_node_os = _obj(racadm_details.get("managed_node_os"))
        racadm_sensor_redundancy = _obj(racadm_details.get("sensor_redundancy"))
        racadm_power_supplies = _rows(racadm_details.get("power_supplies"))
        racadm_embedded_nics = _rows(racadm_system.get("embedded_nics"))

        model = (
            str(dell_details.get("system_model_name", "") or "").strip()
            or str(racadm_system_info.get("system_model", "") or "").strip()
            or str(dell_details.get("controller_model", "") or "").strip()
            or str(raw_facts.get("model", "") or "").strip()
            or "iDRAC"
        )
        display_name = (
            str(raw_facts.get("sys_name", "") or "").strip()
            or str(racadm_rac_info.get("dns_rac_name", "") or "").strip()
            or f"Dell {model}"
        )
        service_tag = str(
            dell_details.get("service_tag", "")
            or dell_details.get("system_service_tag", "")
            or racadm_system_info.get("service_tag", "")
            or raw_facts.get("serial_number", "")
            or ""
        ).strip()
        firmware = str(
            dell_details.get("controller_firmware", "")
            or racadm_rac_info.get("firmware_version", "")
            or raw_facts.get("firmware_version", "")
            or ""
        ).strip()
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
        component_tables = raw_facts.get("idrac_component_tables")
        if not isinstance(component_tables, dict):
            component_tables = {}
        processor_rows = _table_rows(component_tables.get("processors"))
        memory_rows = _table_rows(component_tables.get("memory_devices"))
        power_rows = _table_rows(component_tables.get("power_supplies"))
        cooling_rows = _table_rows(component_tables.get("cooling_devices"))
        temperature_rows = _table_rows(component_tables.get("temperature_probes"))
        if not power_rows and racadm_power_supplies:
            power_rows = [
                {
                    "index": str(row.get("index", "") or "").strip(),
                    "status_code": "3" if str(row.get("cfgserverpowersupplyonlinestatus", "") or "").strip().lower() == "present" else "2",
                    "location_name": f"PSU {str(row.get('index', '') or '').strip()}",
                    "type_code": "",
                    "input_voltage": "",
                    "output_tenths_watts": "",
                    "sensor_state": "",
                    "fqdd": "",
                    "racadm_online_status": str(row.get("cfgserverpowersupplyonlinestatus", "") or "").strip(),
                    "racadm_fw_ver": str(row.get("cfgserverpowersupplyfwver", "") or "").strip(),
                    "racadm_type": str(row.get("cfgserverpowersupplytype", "") or "").strip(),
                    "racadm_max_input_power": str(row.get("cfgserverpowersupplymaxinputpower", "") or "").strip(),
                    "racadm_max_output_power": str(row.get("cfgserverpowersupplymaxoutputpower", "") or "").strip(),
                    "racadm_current_draw": str(row.get("cfgserverpowersupplycurrentdraw", "") or "").strip(),
                }
                for row in racadm_power_supplies
            ]
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

        processor_models = [
            str(row.get("brand_name", "") or row.get("version", "") or "").strip()
            for row in processor_rows
            if str(row.get("brand_name", "") or row.get("version", "") or "").strip()
        ]
        memory_sizes_gb = [_memory_size_gb(row.get("size_kb")) for row in memory_rows]
        memory_sizes_gb = [value for value in memory_sizes_gb if value is not None]
        embedded_nics = [
            row
            for row in racadm_embedded_nics
            if str(row.get("name", "") or "").strip() and str(row.get("mac_address", "") or "").strip()
        ]

        def _worst_component_status(rows: list[dict[str, Any]], code_field: str = "status_code") -> str:
            worst = ""
            for row in rows:
                status = _component_status_from_code(str(row.get(code_field, "") or ""))
                if status == "Critical":
                    return "Critical"
                if status == "Warning":
                    worst = "Warning"
                elif status == "OK" and not worst:
                    worst = "OK"
            return worst

        inventory = {
            "processor_model": processor_models[0] if processor_models else "",
            "processor_vendor": str(processor_rows[0].get("manufacturer", "") or "").strip() if processor_rows else "",
            "processor_count": len(processor_rows) or None,
            "physical_cores": sum(_safe_int(row.get("core_count")) or 0 for row in processor_rows) or None,
            "logical_processors": sum(_safe_int(row.get("thread_count")) or 0 for row in processor_rows) or None,
            "memory_total_gb": round(sum(memory_sizes_gb), 2) if memory_sizes_gb else None,
            "memory_slot_count": len(memory_rows) or None,
            "memory_slots_used": sum(1 for row in memory_rows if (_memory_size_gb(row.get("size_kb")) or 0) > 0) or None,
            "memory_module_count": len(memory_rows) or None,
            "storage_controller_count": len(storage_ctls) if has_storage_mib else None,
            "physical_disk_count": (len(storage_pds) if has_storage_mib else (len(hr_hints) if show_hr_storage else None)),
            "virtual_disk_count": len(storage_vds) if has_storage_mib else None,
            "disk_total_gb": None,
            "network_interface_count": len(embedded_nics) or None,
            "power_supply_count": len(power_rows) or None,
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
            "processor_status": _worst_component_status(processor_rows),
            "memory_status": _worst_component_status(memory_rows),
            "storage_status": worst_storage if (has_storage_mib or hr_hints) else "",
            "power_status": _worst_component_status(power_rows),
            "network_status": "",
            "thermal_status": _worst_component_status(cooling_rows + temperature_rows),
            "power_state": str(racadm_system_info.get("power_status", "") or ""),
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
        table_bits: list[str] = []
        if processor_rows:
            table_bits.append(f"{len(processor_rows)} CPU")
        if memory_rows:
            table_bits.append(f"{len(memory_rows)} DIMM")
        if power_rows:
            table_bits.append(f"{len(power_rows)} PSU")
        if cooling_rows:
            table_bits.append(f"{len(cooling_rows)} fan")
        if temperature_rows:
            table_bits.append(f"{len(temperature_rows)} temperature probe")
        if table_bits:
            health["summary"] = f"{health['summary']} Component tables: {', '.join(table_bits)}."
        power_now = racadm_power.get("cfgserveractualpowerconsumption")
        if power_now:
            health["summary"] = f"{health['summary']} Current draw: {power_now}."
        node_os_name = str(racadm_node_os.get("ifcracmnososname", "") or racadm_system_info.get("os_name", "") or "").strip()
        if node_os_name:
            health["summary"] = f"{health['summary']} Managed OS: {node_os_name}."

        racadm_sel = dell_details.get("racadm_sel")
        if not isinstance(racadm_sel, dict):
            racadm_sel = {}
        sel_entries = [entry for entry in (racadm_sel.get("entries") or []) if isinstance(entry, dict)]
        latest_sel_entry = sel_entries[0] if sel_entries else {}
        latest_sel_message = str(racadm_sel.get("exact_error", "") or latest_sel_entry.get("message", "") or "").strip()
        latest_sel_timestamp = str(racadm_sel.get("exact_timestamp", "") or latest_sel_entry.get("event_time", "") or "").strip()
        if latest_sel_message:
            suffix = f" Latest SEL event: {latest_sel_message}."
            if latest_sel_timestamp:
                suffix = f" Latest SEL event at {latest_sel_timestamp}: {latest_sel_message}."
            health["summary"] = f"{health['summary']}{suffix}"

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
                    "bios_version": str(racadm_version.get("bios_version", "") or racadm_system_info.get("system_bios_version", "") or ""),
                    "idrac_version": str(racadm_version.get("idrac_version", "") or ""),
                    "usc_version": str(racadm_version.get("usc_version", "") or ""),
                    "power_status": str(racadm_system_info.get("power_status", "") or ""),
                    "managed_os_name": str(racadm_node_os.get("ifcracmnososname", "") or racadm_system_info.get("os_name", "") or ""),
                    "managed_os_hostname": str(racadm_node_os.get("ifcracmnoshostname", "") or racadm_system_info.get("host_name", "") or ""),
                    "actual_power_consumption": str(racadm_power.get("cfgserveractualpowerconsumption", "") or ""),
                    "peak_power_consumption": str(racadm_power.get("cfgserverpeakpowerconsumption", "") or ""),
                    "peak_power_timestamp": str(racadm_power.get("cfgserverpeakpowerconsumptiontimestamp", "") or ""),
                    "power_cap_watts": str(racadm_power.get("cfgserverpowercapwatts", "") or ""),
                    "sensor_redundancy_policy": str(racadm_sensor_redundancy.get("cfgsensorredundancypolicy", "") or ""),
                },
            }
        ]

        for row in processor_rows:
            code = str(row.get("status_code", "") or "").strip()
            brand = str(row.get("brand_name", "") or row.get("version", "") or "").strip()
            fqdd = str(row.get("fqdd", "") or row.get("index", "") or "").strip()
            components.append(
                {
                    "component_type": "cpu",
                    "name": fqdd or brand or "Processor",
                    "slot": fqdd,
                    "model": brand,
                    "manufacturer": str(row.get("manufacturer", "") or "").strip(),
                    "serial_number": "",
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "source": "idrac_processor_table",
                        "snmp_index": row.get("index", ""),
                        "status_code": code,
                        "type_code": str(row.get("type_code", "") or ""),
                        "current_speed_mhz": _safe_int(row.get("current_speed_mhz")),
                        "core_count": _safe_int(row.get("core_count")),
                        "thread_count": _safe_int(row.get("thread_count")),
                        "version": str(row.get("version", "") or ""),
                    },
                }
            )

        for row in memory_rows:
            code = str(row.get("status_code", "") or "").strip()
            location = str(row.get("location_name", "") or row.get("bank_location_name", "") or row.get("index", "") or "").strip()
            speed_ns = _safe_int(row.get("speed_ns"))
            components.append(
                {
                    "component_type": "memory_module",
                    "name": location or "Memory DIMM",
                    "slot": location,
                    "model": _label_from_map(MEMORY_TYPE_BY_CODE, row.get("type_code")),
                    "manufacturer": str(row.get("manufacturer", "") or "").strip(),
                    "serial_number": "",
                    "firmware_version": "",
                    "capacity_gb": _memory_size_gb(row.get("size_kb")),
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "source": "idrac_memory_table",
                        "snmp_index": row.get("index", ""),
                        "status_code": code,
                        "type_code": str(row.get("type_code", "") or ""),
                        "bank_location_name": str(row.get("bank_location_name", "") or ""),
                        "part_number": str(row.get("part_number", "") or ""),
                        "size_kb": _safe_int(row.get("size_kb")),
                        "operating_speed_mhz": speed_ns,
                        "speed_ns": speed_ns,
                        "memory_type": _label_from_map(MEMORY_TYPE_BY_CODE, row.get("type_code")),
                    },
                }
            )

        for row in power_rows:
            code = str(row.get("status_code", "") or "").strip()
            location = str(row.get("location_name", "") or row.get("fqdd", "") or row.get("index", "") or "").strip()
            racadm_type = str(row.get("racadm_type", "") or "").strip()
            racadm_fw_ver = str(row.get("racadm_fw_ver", "") or "").strip()
            components.append(
                {
                    "component_type": "power_supply",
                    "name": location or "Power Supply",
                    "slot": location,
                    "model": racadm_type or _label_from_map(POWER_SUPPLY_TYPE_BY_CODE, row.get("type_code")),
                    "manufacturer": "Dell",
                    "serial_number": "",
                    "firmware_version": racadm_fw_ver,
                    "capacity_gb": None,
                    "status": str(row.get("racadm_online_status", "") or _component_status_from_code(code)),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "source": "idrac_power_supply_table" if str(row.get("type_code", "") or "").strip() else "idrac_racadm_power_supply",
                        "snmp_index": row.get("index", ""),
                        "status_code": code,
                        "type_code": str(row.get("type_code", "") or ""),
                        "power_supply_type": racadm_type or _label_from_map(POWER_SUPPLY_TYPE_BY_CODE, row.get("type_code")),
                        "output_watts": _power_watts(row.get("output_tenths_watts")),
                        "input_voltage": _safe_int(row.get("input_voltage")),
                        "sensor_state": str(row.get("sensor_state", "") or ""),
                        "fqdd": str(row.get("fqdd", "") or ""),
                        "online_status": str(row.get("racadm_online_status", "") or ""),
                        "max_input_power": str(row.get("racadm_max_input_power", "") or ""),
                        "max_output_power": str(row.get("racadm_max_output_power", "") or ""),
                        "current_draw": str(row.get("racadm_current_draw", "") or ""),
                    },
                }
            )

        for row in embedded_nics:
            name = str(row.get("name", "") or "").strip()
            mac_address = str(row.get("mac_address", "") or "").strip()
            if not name or not mac_address:
                continue
            components.append(
                {
                    "component_type": "nic",
                    "name": name,
                    "slot": name.split()[0] if " " in name else name,
                    "model": "Embedded NIC",
                    "manufacturer": "Dell",
                    "serial_number": mac_address,
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": "OK",
                    "health": "Observed",
                    "extra_json": {
                        "source": "idrac_racadm_getsysinfo",
                        "mac_address": mac_address,
                    },
                }
            )

        for row in cooling_rows:
            code = str(row.get("status_code", "") or "").strip()
            location = str(row.get("location_name", "") or row.get("index", "") or "").strip()
            components.append(
                {
                    "component_type": "fan",
                    "name": location or "Cooling Device",
                    "slot": location,
                    "model": _label_from_map(COOLING_TYPE_BY_CODE, row.get("type_code")),
                    "manufacturer": "",
                    "serial_number": "",
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "source": "idrac_cooling_device_table",
                        "snmp_index": row.get("index", ""),
                        "status_code": code,
                        "type_code": str(row.get("type_code", "") or ""),
                        "cooling_type": _label_from_map(COOLING_TYPE_BY_CODE, row.get("type_code")),
                        "reading_rpm": _safe_int(row.get("reading_rpm")),
                    },
                }
            )

        for row in temperature_rows:
            code = str(row.get("status_code", "") or "").strip()
            location = str(row.get("location_name", "") or row.get("index", "") or "").strip()
            components.append(
                {
                    "component_type": "temperature_probe",
                    "name": location or "Temperature Probe",
                    "slot": location,
                    "model": _label_from_map(TEMPERATURE_TYPE_BY_CODE, row.get("type_code")),
                    "manufacturer": "",
                    "serial_number": "",
                    "firmware_version": "",
                    "capacity_gb": None,
                    "status": _component_status_from_code(code),
                    "health": _dell_snmp_status_label(code),
                    "extra_json": {
                        "source": "idrac_temperature_probe_table",
                        "snmp_index": row.get("index", ""),
                        "status_code": code,
                        "type_code": str(row.get("type_code", "") or ""),
                        "probe_type": _label_from_map(TEMPERATURE_TYPE_BY_CODE, row.get("type_code")),
                        "reading_celsius": _temperature_c(row.get("reading_tenths_c")),
                        "reading_tenths_c": _safe_int(row.get("reading_tenths_c")),
                    },
                }
            )

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

        for entry in sel_entries:
            message = str(entry.get("message", "") or "").strip()
            if not message:
                continue
            record_id = str(entry.get("record_id", "") or "").strip()
            event_time = str(entry.get("event_time", "") or "").strip() or None
            raw_severity = str(entry.get("severity", "") or "").strip()
            alerts.append(
                {
                    "source": "legacy_idrac_racadm",
                    "severity": _alert_severity(raw_severity),
                    "code": f"idrac_sel_record_{record_id}" if record_id else "idrac_sel_event",
                    "message": message,
                    "status": "recorded",
                    "first_seen_at": event_time,
                    "last_seen_at": event_time,
                    "cleared_at": None,
                    "extra_json": {
                        "history_entry": True,
                        "event_time": event_time or "",
                        "record_id": record_id,
                        "raw_severity": raw_severity,
                        "source_command": str(racadm_sel.get("command", "") or ""),
                    },
                }
            )

        health["alert_count"] = len(alerts) or 0

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
                    "last_alert_message": latest_sel_message,
                    "last_alert_time": latest_sel_timestamp,
                    "racadm_sel_entries": sel_entries,
                    "storage_via_snmp": bool(has_storage_mib),
                    "storage_via_hr_hints": bool(show_hr_storage),
                },
            ),
        }
