"""VMware ESXi SNMP template."""
from __future__ import annotations

import re
from typing import Any

from proxy_agent.templates.base import DeviceTemplate

HR_DEVICE_PROCESSOR = "1.3.6.1.2.1.25.3.1.3"
HR_DEVICE_NETWORK = "1.3.6.1.2.1.25.3.1.4"
HR_DEVICE_DISK = "1.3.6.1.2.1.25.3.1.6"

HR_STORAGE_FIXED_DISK = "1.3.6.1.2.1.25.2.1.4"

HBA_STATUS_MAP = {
    "0": "unknown",
    "1": "other",
    "2": "ok",
    "3": "warning",
    "4": "failed",
    "5": "offline",
}


def _to_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _bytes_to_gb(value: int) -> float:
    return round(value / (1024 ** 3), 2)


def _parse_esxi_version(text: str) -> str:
    match = re.search(r"(ESXi\s+[0-9.]+(?:\s+build-[0-9]+)?)", text, re.IGNORECASE)
    return match.group(1) if match else ""


def _looks_like_real_version(text: str) -> bool:
    value = text.strip()
    return bool(value) and (value.lower().startswith("esxi ") or "." in value or "build" in value.lower())


def _normalize_cpu_model(text: str) -> str:
    if "Node:" in text:
        return text.split("Node:", 1)[-1].strip().split(" ", 1)[-1].strip()
    return text.strip()


def _choose_display_name(raw_facts: dict[str, Any]) -> str:
    sys_name = str(raw_facts.get("sys_name", "") or "").strip()
    if sys_name and sys_name.lower() not in {"localhost", "localhost.localdomain"}:
        return sys_name
    target_name = str(raw_facts.get("name", "") or "").strip()
    if target_name:
        return target_name
    return str(raw_facts.get("management_ip", "") or "").strip() or "ESXi host"


def _perccli_status(value: Any) -> str:
    state = str(value or "").strip().lower()
    if state in {"optl", "onln", "ok", "ugood"}:
        return "OK"
    if state in {"dgrd", "pdgd", "ubunsp", "warning"}:
        return "Warning"
    if state in {"offln", "failed", "crit", "critical"}:
        return "Critical"
    return "Unknown"


class VmwareEsxiTemplate(DeviceTemplate):
    key = "vmware_esxi"
    display_name = "VMware ESXi Host"
    supported_protocols = ["snmp"]

    def match(self, raw_facts: dict[str, Any]) -> bool:
        if str(raw_facts.get("protocol", "")).lower() != "snmp":
            return False
        combined = " ".join(
            [
                str(raw_facts.get("sys_descr", "") or ""),
                str(raw_facts.get("sys_name", "") or ""),
                str(raw_facts.get("model", "") or ""),
            ]
        ).lower()
        return "vmware esxi" in combined or self.key == str(raw_facts.get("template_key", "")).lower()

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        details = raw_facts.get("esxi_details")
        if not isinstance(details, dict):
            details = {}

        devices = details.get("devices")
        if not isinstance(devices, list):
            devices = []
        storage = details.get("storage")
        if not isinstance(storage, list):
            storage = []
        interfaces = details.get("interfaces")
        if not isinstance(interfaces, list):
            interfaces = []
        hbas = details.get("hbas")
        if not isinstance(hbas, list):
            hbas = []
        vmware_metrics = details.get("vmware_metrics")
        if not isinstance(vmware_metrics, dict):
            vmware_metrics = {}
        perccli = details.get("perccli")
        if not isinstance(perccli, dict):
            perccli = {}

        processors = [item for item in devices if str(item.get("type", "")) == HR_DEVICE_PROCESSOR]
        processor_models = []
        package_ids = set()
        for processor in processors:
            desc = str(processor.get("description", "") or "")
            if desc:
                processor_models.append(_normalize_cpu_model(desc))
            pkg_match = re.search(r"Pkg/ID/Node:\s*([0-9]+)", desc)
            if pkg_match:
                package_ids.add(pkg_match.group(1))

        memory_total_kb = _to_int(vmware_metrics.get("memory_total_kb"))
        memory_used_kb = _to_int(vmware_metrics.get("memory_used_kb"))
        memory_free_kb = _to_int(vmware_metrics.get("memory_free_kb"))
        if memory_total_kb is None:
            for item in storage:
                if str(item.get("description", "")).strip().lower() == "real memory":
                    alloc = _to_int(item.get("allocation_units")) or 0
                    size = _to_int(item.get("size")) or 0
                    if alloc and size:
                        memory_total_kb = int((alloc * size) / 1024)
                    used = _to_int(item.get("used")) or 0
                    if alloc and used:
                        memory_used_kb = int((alloc * used) / 1024)
                    break

        datastore_components = []
        datastore_total_bytes = 0
        datastore_used_bytes = 0
        for item in storage:
            description = str(item.get("description", "") or "").strip()
            if not description.startswith("/vmfs/volumes/"):
                continue
            alloc = _to_int(item.get("allocation_units")) or 0
            size = _to_int(item.get("size")) or 0
            used = _to_int(item.get("used")) or 0
            total_bytes = alloc * size
            used_bytes = alloc * used
            datastore_total_bytes += total_bytes
            datastore_used_bytes += used_bytes
            datastore_components.append(
                {
                    "component_type": "datastore",
                    "name": description.rsplit("/", 1)[-1] or description,
                    "status": "OK",
                    "capacity_gb": _bytes_to_gb(total_bytes),
                    "used_gb": _bytes_to_gb(used_bytes),
                    "raw": item,
                }
            )

        nic_components = []
        nic_count = 0
        preferred_mac = ""
        for item in interfaces:
            name = str(item.get("name", "") or "").strip()
            mac = str(item.get("mac_address", "") or "").strip()
            if not name:
                continue
            lowered = name.lower()
            if "vmnic" in lowered:
                nic_count += 1
                if mac and not preferred_mac:
                    preferred_mac = mac
            elif "vmk" in lowered and mac:
                preferred_mac = mac
            nic_components.append(
                {
                    "component_type": "network_interface",
                    "name": name,
                    "status": "OK",
                    "mac_address": mac,
                    "raw": item,
                }
            )

        hba_components = []
        hba_health = []
        for item in hbas:
            raw_status = str(item.get("status", "") or "").strip()
            status = HBA_STATUS_MAP.get(raw_status, "unknown")
            hba_health.append(status)
            hba_components.append(
                {
                    "component_type": "storage_controller",
                    "name": str(item.get("name", "") or "").strip() or f"HBA {item.get('index', '')}",
                    "status": status.upper() if status != "ok" else "OK",
                    "model": str(item.get("model", "") or "").strip(),
                    "driver": str(item.get("driver", "") or "").strip(),
                    "pci_address": str(item.get("pci", "") or "").strip(),
                    "raw": item,
                }
            )

        perccli_controller = perccli.get("controller")
        if not isinstance(perccli_controller, dict):
            perccli_controller = {}
        perccli_physical_disks = perccli.get("physical_disks")
        if not isinstance(perccli_physical_disks, list):
            perccli_physical_disks = []
        perccli_virtual_disks = perccli.get("virtual_disks")
        if not isinstance(perccli_virtual_disks, list):
            perccli_virtual_disks = []

        raid_controller_components = []
        if perccli_controller.get("product_name"):
            raid_controller_components.append(
                {
                    "component_type": "raid_controller",
                    "name": str(perccli_controller.get("product_name", "") or "").strip(),
                    "status": _perccli_status(perccli_controller.get("health")),
                    "serial_number": str(perccli_controller.get("serial_number", "") or "").strip(),
                    "firmware_version": str(perccli_controller.get("firmware_version", "") or "").strip(),
                    "model": str(perccli_controller.get("product_name", "") or "").strip(),
                    "raw": perccli_controller,
                }
            )

        physical_disk_components = []
        for disk in perccli_physical_disks:
            if not isinstance(disk, dict):
                continue
            enclosure = str(disk.get("enclosure_id", "") or "").strip()
            slot = str(disk.get("slot", "") or "").strip()
            slot_label = ":".join(part for part in [enclosure, slot] if part) or "unknown"
            physical_disk_components.append(
                {
                    "component_type": "physical_disk",
                    "name": f"Disk {slot_label}",
                    "status": _perccli_status(disk.get("state")),
                    "serial_number": str(disk.get("serial_number", "") or "").strip(),
                    "firmware_version": str(disk.get("firmware_revision", "") or "").strip(),
                    "model": str(disk.get("model", "") or "").strip(),
                    "capacity_gb": disk.get("size_gb"),
                    "slot": slot_label,
                    "raw": disk,
                }
            )

        virtual_disk_components = []
        for array in perccli_virtual_disks:
            if not isinstance(array, dict):
                continue
            vd = str(array.get("virtual_disk", "") or "").strip()
            raid_type = str(array.get("raid_type", "") or "").strip()
            display = " ".join(part for part in [f"VD{vd}" if vd else "", raid_type] if part).strip() or "Virtual Disk"
            virtual_disk_components.append(
                {
                    "component_type": "virtual_disk",
                    "name": display,
                    "status": _perccli_status(array.get("state")),
                    "capacity_gb": array.get("size_gb"),
                    "raid_type": raid_type,
                    "raw": array,
                }
            )

        sensor_problem_count = 0
        for item in devices:
            status_code = str(item.get("status", "") or "").strip()
            if status_code in {"3", "4", "5"}:
                sensor_problem_count += 1

        health_state = "OK"
        if any(state in {"warning", "offline"} for state in hba_health) or sensor_problem_count:
            health_state = "Warning"
        if any(state == "failed" for state in hba_health):
            health_state = "Critical"

        cpu_model = processor_models[0] if processor_models else ""
        version_from_vmware = str(vmware_metrics.get("product_version", "") or "").strip()
        version_from_sysdescr = _parse_esxi_version(str(raw_facts.get("sys_descr", "") or ""))
        esxi_version = version_from_vmware if _looks_like_real_version(version_from_vmware) else version_from_sysdescr
        firmware_version = str(raw_facts.get("firmware_version", "") or "").strip() or esxi_version
        mac_address = str(raw_facts.get("mac_address", "") or "").strip() or preferred_mac

        physical_disk_total_gb = sum(
            float(item.get("size_gb", 0) or 0)
            for item in perccli_physical_disks
            if isinstance(item, dict) and item.get("size_gb")
        )
        virtual_disk_total_gb = sum(
            float(item.get("size_gb", 0) or 0)
            for item in perccli_virtual_disks
            if isinstance(item, dict) and item.get("size_gb")
        )
        raid_types = sorted(
            {
                str(item.get("raid_type", "") or "").strip()
                for item in perccli_virtual_disks
                if isinstance(item, dict) and str(item.get("raid_type", "") or "").strip()
            }
        )

        inventory = {
            "hypervisor": "VMware ESXi",
            "logical_processors": len(processors) or None,
            "processor_packages": len(package_ids) or None,
            "processor_model": cpu_model or None,
            "memory_total_gb": _bytes_to_gb(memory_total_kb * 1024) if memory_total_kb is not None else None,
            "memory_used_gb": _bytes_to_gb(memory_used_kb * 1024) if memory_used_kb is not None else None,
            "memory_free_gb": _bytes_to_gb(memory_free_kb * 1024) if memory_free_kb is not None else None,
            "datastore_count": len(datastore_components) or None,
            "datastore_total_gb": _bytes_to_gb(datastore_total_bytes) if datastore_total_bytes else None,
            "datastore_used_gb": _bytes_to_gb(datastore_used_bytes) if datastore_used_bytes else None,
            "network_interface_count": nic_count or None,
            "storage_controller_count": (len(hba_components) + len(raid_controller_components)) or None,
            "physical_disk_count": len(perccli_physical_disks) or None,
            "virtual_disk_count": len(perccli_virtual_disks) or None,
            "disk_total_gb": round(physical_disk_total_gb, 2) if physical_disk_total_gb else None,
            "raid_summary": ", ".join(raid_types) if raid_types else None,
        }
        inventory = {key: value for key, value in inventory.items() if value is not None}

        components = []
        components.extend(hba_components)
        components.extend(raid_controller_components)
        components.extend(physical_disk_components)
        components.extend(virtual_disk_components)
        components.extend(nic_components)
        components.extend(datastore_components)

        summary_bits = [
            f"{len(processors)} logical CPU(s)",
            f"{len(datastore_components)} datastore(s)",
            f"{len(hba_components) + len(raid_controller_components)} storage controller(s)",
        ]
        if perccli_physical_disks:
            summary_bits.append(f"{len(perccli_physical_disks)} physical disk(s)")
        if perccli_virtual_disks:
            summary_bits.append(f"{len(perccli_virtual_disks)} virtual disk(s)")
        health = {
            "overall_status": health_state,
            "summary": "ESXi host reachable via SNMP; " + ", ".join(summary_bits) + ".",
            "sensor_problem_count": sensor_problem_count,
        }

        status = "Healthy" if health_state == "OK" else health_state
        return {
            "asset_class": "server",
            "display_name": _choose_display_name(raw_facts),
            "vendor": "VMware",
            "model": str(raw_facts.get("model", "") or "").strip() or "ESXi host",
            "serial_number": str(raw_facts.get("serial_number", "") or "").strip(),
            "firmware_version": firmware_version,
            "ip_address": str(raw_facts.get("ip_address", "") or "").strip(),
            "management_ip": str(raw_facts.get("management_ip", "") or "").strip(),
            "mac_address": mac_address,
            "status": status,
            "inventory": inventory,
            "components": components,
            "health": health,
            "alerts": [],
            "raw_facts": self.build_raw_facts(
                raw_facts,
                {
                    "vendor": "VMware",
                    "hypervisor": "VMware ESXi",
                    "esxi_version": esxi_version,
                    "raid_inventory_source": "esxi_perccli" if perccli_controller else "",
                },
            ),
        }
