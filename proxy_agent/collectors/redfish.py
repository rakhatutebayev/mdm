"""Raw Redfish transport collector for Proxy Agent."""
from __future__ import annotations

import ssl
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.poolmanager import PoolManager
from urllib3.util.ssl_ import create_urllib3_context


@dataclass
class RedfishTarget:
    name: str
    base_url: str
    username: str
    password: str
    verify_tls: bool = True
    timeout_s: float = 10.0
    template_key: str = ""
    system_path: str = ""
    manager_path: str = ""


class LegacyTlsAdapter(HTTPAdapter):
    """Allow connections to older BMC/iDRAC TLS stacks when verify is disabled."""

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        context = create_urllib3_context(ciphers="DEFAULT:@SECLEVEL=1")
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        context.check_hostname = False
        self.poolmanager = PoolManager(
            num_pools=connections,
            maxsize=maxsize,
            block=block,
            ssl_context=context,
            **pool_kwargs,
        )

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        context = create_urllib3_context(ciphers="DEFAULT:@SECLEVEL=1")
        if hasattr(ssl, "OP_LEGACY_SERVER_CONNECT"):
            context.options |= ssl.OP_LEGACY_SERVER_CONNECT
        context.check_hostname = False
        proxy_kwargs["ssl_context"] = context
        return super().proxy_manager_for(proxy, **proxy_kwargs)


def _normalize_base_url(value: str) -> str:
    return value.rstrip("/")


def _host_from_base_url(base_url: str) -> str:
    host = base_url.split("://", 1)[-1].split("/", 1)[0]
    return host.split(":", 1)[0]


def _to_url(base_url: str, ref: str) -> str:
    if ref.startswith("http://") or ref.startswith("https://"):
        return ref
    return f"{base_url}{ref}"


def _get_json(session: requests.Session, url: str, timeout_s: float) -> dict[str, Any]:
    response = session.get(url, timeout=timeout_s)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError(f"Unexpected Redfish payload from {url}")
    return payload


def _safe_get_json(session: requests.Session, url: str, timeout_s: float) -> dict[str, Any]:
    try:
        return _get_json(session, url, timeout_s)
    except Exception:
        return {}


def _resolve_member_url(base_url: str, entry: dict[str, Any], explicit_path: str, root_key: str) -> str:
    if explicit_path:
        if explicit_path.startswith("http://") or explicit_path.startswith("https://"):
            return explicit_path
        return f"{base_url}{explicit_path}"

    endpoint = entry.get(root_key)
    if not isinstance(endpoint, dict):
        return ""
    members = endpoint.get("Members")
    if isinstance(members, list) and members:
        first = members[0]
        if isinstance(first, dict):
            odata_id = str(first.get("@odata.id", "") or "")
            if odata_id:
                return f"{base_url}{odata_id}"
    endpoint_id = str(endpoint.get("@odata.id", "") or "")
    if endpoint_id:
        return f"{base_url}{endpoint_id}"
    return ""


def _resolve_ref_url(base_url: str, ref: Any) -> str:
    if isinstance(ref, str) and ref:
        return _to_url(base_url, ref)
    if isinstance(ref, dict):
        odata_id = str(ref.get("@odata.id", "") or "")
        if odata_id:
            return _to_url(base_url, odata_id)
    return ""


def _fetch_members(session: requests.Session, base_url: str, ref: Any, timeout_s: float) -> list[dict[str, Any]]:
    if isinstance(ref, list):
        items: list[dict[str, Any]] = []
        for entry in ref:
            url = _resolve_ref_url(base_url, entry)
            if not url:
                continue
            payload = _safe_get_json(session, url, timeout_s)
            if payload:
                items.append(payload)
        return items

    url = _resolve_ref_url(base_url, ref)
    if not url:
        return []

    payload = _safe_get_json(session, url, timeout_s)
    if not payload:
        return []

    members = payload.get("Members")
    if not isinstance(members, list):
        return [payload]

    items: list[dict[str, Any]] = []
    for entry in members:
        member_url = _resolve_ref_url(base_url, entry)
        if not member_url:
            continue
        member_payload = _safe_get_json(session, member_url, timeout_s)
        if member_payload:
            items.append(member_payload)
    return items


def _fetch_linked_resource(session: requests.Session, base_url: str, data: dict[str, Any], key: str, timeout_s: float) -> dict[str, Any]:
    return _safe_get_json(session, _resolve_ref_url(base_url, data.get(key)), timeout_s)


def _health_value(data: dict[str, Any]) -> str:
    status = data.get("Status")
    if isinstance(status, dict):
        return str(status.get("Health", "") or status.get("HealthRollup", "") or "")
    return ""


def _state_value(data: dict[str, Any]) -> str:
    status = data.get("Status")
    if isinstance(status, dict):
        return str(status.get("State", "") or "")
    return str(data.get("State", "") or data.get("LinkStatus", "") or data.get("PowerState", "") or "")


def _status_rank(value: str) -> int:
    text = value.strip().lower()
    if not text:
        return 0
    if text in {"critical", "failed", "error", "offline", "absent"}:
        return 4
    if text in {"warning", "degraded", "noncritical"}:
        return 3
    if text in {"unknown", "starting", "stopping"}:
        return 2
    if text in {"ok", "healthy", "enabled", "up", "online"}:
        return 1
    return 2


def _rollup_status(values: list[str]) -> str:
    present = [value.strip() for value in values if str(value).strip()]
    if not present:
        return ""
    return max(present, key=_status_rank)


def _capacity_gb(payload: dict[str, Any]) -> float | None:
    raw_bytes = payload.get("CapacityBytes")
    if isinstance(raw_bytes, (int, float)) and raw_bytes > 0:
        return round(float(raw_bytes) / (1024 ** 3), 2)

    mib = payload.get("CapacityMiB")
    if isinstance(mib, (int, float)) and mib > 0:
        return round(float(mib) / 1024, 2)

    gb = payload.get("CapacityGB") or payload.get("CapacityGib")
    if isinstance(gb, (int, float)) and gb > 0:
        return round(float(gb), 2)

    return None


def _iso_or_empty(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return text


def collect_target(target: RedfishTarget) -> list[dict[str, Any]]:
    base_url = _normalize_base_url(target.base_url)
    host = _host_from_base_url(base_url)
    session = requests.Session()
    session.auth = (target.username, target.password)
    session.verify = target.verify_tls
    session.headers.update({"Accept": "application/json"})
    if not target.verify_tls:
        session.mount("https://", LegacyTlsAdapter())

    try:
        service_root = _get_json(session, f"{base_url}/redfish/v1", target.timeout_s)
        system_url = _resolve_member_url(base_url, service_root, target.system_path, "Systems")
        manager_url = _resolve_member_url(base_url, service_root, target.manager_path, "Managers")

        system_data = _get_json(session, system_url, target.timeout_s) if system_url else {}
        manager_data = _get_json(session, manager_url, target.timeout_s) if manager_url else {}
        chassis_members = _fetch_members(session, base_url, service_root.get("Chassis"), target.timeout_s)
        chassis_data = chassis_members[0] if chassis_members else {}

        processors = _fetch_members(session, base_url, system_data.get("Processors"), target.timeout_s)
        memory_modules = _fetch_members(session, base_url, system_data.get("Memory"), target.timeout_s)
        storage_members = _fetch_members(session, base_url, system_data.get("Storage"), target.timeout_s)
        network_ifaces = _fetch_members(
            session,
            base_url,
            manager_data.get("EthernetInterfaces") or system_data.get("EthernetInterfaces"),
            target.timeout_s,
        )
        power_data = _fetch_linked_resource(session, base_url, chassis_data, "Power", target.timeout_s)
        thermal_data = _fetch_linked_resource(session, base_url, chassis_data, "Thermal", target.timeout_s)

        storage_controllers: list[dict[str, Any]] = []
        physical_disks: list[dict[str, Any]] = []
        virtual_disks: list[dict[str, Any]] = []

        for storage in storage_members:
            controllers = storage.get("StorageControllers")
            if isinstance(controllers, list):
                for controller in controllers:
                    if isinstance(controller, dict):
                        storage_controllers.append(controller)
            else:
                storage_controllers.append(storage)
            physical_disks.extend(_fetch_members(session, base_url, storage.get("Drives"), target.timeout_s))
            virtual_disks.extend(_fetch_members(session, base_url, storage.get("Volumes"), target.timeout_s))

        power_supplies = power_data.get("PowerSupplies", []) if isinstance(power_data.get("PowerSupplies"), list) else []
        temperatures = thermal_data.get("Temperatures", []) if isinstance(thermal_data.get("Temperatures"), list) else []

        log_services = _fetch_members(
            session,
            base_url,
            manager_data.get("LogServices") or system_data.get("LogServices"),
            target.timeout_s,
        )
        alerts: list[dict[str, Any]] = []
        for service in log_services[:4]:
            entries = _fetch_members(session, base_url, service.get("Entries"), target.timeout_s)
            for entry in entries[:20]:
                message = str(entry.get("Message", "") or entry.get("Name", "") or "").strip()
                if not message:
                    continue
                alerts.append(
                    {
                        "source": str(service.get("Name", "") or service.get("Id", "") or "redfish"),
                        "severity": str(entry.get("Severity", "") or entry.get("EntryType", "") or "info"),
                        "code": str(entry.get("MessageId", "") or entry.get("Id", "") or ""),
                        "message": message,
                        "status": "active",
                        "first_seen_at": _iso_or_empty(entry.get("Created")),
                        "last_seen_at": _iso_or_empty(entry.get("Created")),
                        "cleared_at": None,
                        "extra_json": {
                            "entry_type": str(entry.get("EntryType", "") or ""),
                            "sensor_number": str(entry.get("SensorNumber", "") or ""),
                        },
                    }
                )

        components: list[dict[str, Any]] = []

        for cpu in processors:
            components.append(
                {
                    "component_type": "cpu",
                    "name": str(cpu.get("Name", "") or cpu.get("Id", "") or "CPU"),
                    "slot": str(cpu.get("Socket", "") or cpu.get("Id", "") or ""),
                    "model": str(cpu.get("Model", "") or cpu.get("ProcessorType", "") or cpu.get("Name", "") or ""),
                    "manufacturer": str(cpu.get("Manufacturer", "") or ""),
                    "serial_number": str(cpu.get("SerialNumber", "") or ""),
                    "firmware_version": str(cpu.get("MicrocodeInfo", "") or ""),
                    "capacity_gb": None,
                    "status": _state_value(cpu),
                    "health": _health_value(cpu),
                    "extra_json": {
                        "cores": cpu.get("TotalCores"),
                        "threads": cpu.get("TotalThreads"),
                        "max_speed_mhz": cpu.get("MaxSpeedMHz"),
                    },
                }
            )

        for module in memory_modules:
            capacity_gb = _capacity_gb(module)
            components.append(
                {
                    "component_type": "memory_module",
                    "name": str(module.get("Name", "") or module.get("Id", "") or "Memory DIMM"),
                    "slot": str(module.get("DeviceLocator", "") or module.get("SocketLocator", "") or module.get("Id", "") or ""),
                    "model": str(module.get("PartNumber", "") or module.get("MemoryDeviceType", "") or ""),
                    "manufacturer": str(module.get("Manufacturer", "") or ""),
                    "serial_number": str(module.get("SerialNumber", "") or ""),
                    "firmware_version": "",
                    "capacity_gb": capacity_gb,
                    "status": _state_value(module),
                    "health": _health_value(module),
                    "extra_json": {
                        "operating_speed_mhz": module.get("OperatingSpeedMhz"),
                        "memory_type": module.get("MemoryDeviceType"),
                    },
                }
            )

        for controller in storage_controllers:
            components.append(
                {
                    "component_type": "raid_controller",
                    "name": str(controller.get("Name", "") or controller.get("Id", "") or "Storage Controller"),
                    "slot": str(controller.get("Location", "") or controller.get("Id", "") or ""),
                    "model": str(controller.get("Model", "") or controller.get("Name", "") or ""),
                    "manufacturer": str(controller.get("Manufacturer", "") or ""),
                    "serial_number": str(controller.get("SerialNumber", "") or ""),
                    "firmware_version": str(controller.get("FirmwareVersion", "") or ""),
                    "capacity_gb": None,
                    "status": _state_value(controller),
                    "health": _health_value(controller),
                    "extra_json": {
                        "supported_raid_types": controller.get("SupportedRAIDTypes"),
                    },
                }
            )

        for disk in physical_disks:
            components.append(
                {
                    "component_type": "physical_disk",
                    "name": str(disk.get("Name", "") or disk.get("Id", "") or "Physical Disk"),
                    "slot": str(disk.get("Location", "") or disk.get("Id", "") or ""),
                    "model": str(disk.get("Model", "") or disk.get("PartNumber", "") or ""),
                    "manufacturer": str(disk.get("Manufacturer", "") or ""),
                    "serial_number": str(disk.get("SerialNumber", "") or ""),
                    "firmware_version": str(disk.get("Revision", "") or disk.get("FirmwareVersion", "") or ""),
                    "capacity_gb": _capacity_gb(disk),
                    "status": _state_value(disk),
                    "health": _health_value(disk),
                    "extra_json": {
                        "media_type": str(disk.get("MediaType", "") or ""),
                        "protocol": str(disk.get("Protocol", "") or ""),
                        "predicted_media_life_left_percent": disk.get("PredictedMediaLifeLeftPercent"),
                    },
                }
            )

        for volume in virtual_disks:
            components.append(
                {
                    "component_type": "virtual_disk",
                    "name": str(volume.get("Name", "") or volume.get("Id", "") or "Virtual Disk"),
                    "slot": str(volume.get("Id", "") or ""),
                    "model": str(volume.get("RAIDType", "") or volume.get("VolumeType", "") or "Virtual Disk"),
                    "manufacturer": "",
                    "serial_number": str(volume.get("Identifiers", "") or ""),
                    "firmware_version": "",
                    "capacity_gb": _capacity_gb(volume),
                    "status": _state_value(volume),
                    "health": _health_value(volume),
                    "extra_json": {
                        "raid_type": str(volume.get("RAIDType", "") or ""),
                        "volume_type": str(volume.get("VolumeType", "") or ""),
                    },
                }
            )

        for nic in network_ifaces:
            components.append(
                {
                    "component_type": "nic",
                    "name": str(nic.get("Name", "") or nic.get("Id", "") or "NIC"),
                    "slot": str(nic.get("Id", "") or ""),
                    "model": str(nic.get("Description", "") or nic.get("Name", "") or ""),
                    "manufacturer": str(nic.get("Manufacturer", "") or ""),
                    "serial_number": str(nic.get("PermanentMACAddress", "") or nic.get("MACAddress", "") or ""),
                    "firmware_version": str(nic.get("FirmwareVersion", "") or ""),
                    "capacity_gb": None,
                    "status": _state_value(nic),
                    "health": _health_value(nic),
                    "extra_json": {
                        "mac_address": str(nic.get("MACAddress", "") or nic.get("PermanentMACAddress", "") or ""),
                        "speed_mbps": nic.get("SpeedMbps"),
                        "link_status": str(nic.get("LinkStatus", "") or ""),
                    },
                }
            )

        for psu in power_supplies:
            components.append(
                {
                    "component_type": "power_supply",
                    "name": str(psu.get("Name", "") or psu.get("MemberId", "") or "PSU"),
                    "slot": str(psu.get("MemberId", "") or ""),
                    "model": str(psu.get("Model", "") or psu.get("Name", "") or ""),
                    "manufacturer": str(psu.get("Manufacturer", "") or ""),
                    "serial_number": str(psu.get("SerialNumber", "") or ""),
                    "firmware_version": str(psu.get("FirmwareVersion", "") or ""),
                    "capacity_gb": None,
                    "status": _state_value(psu),
                    "health": _health_value(psu),
                    "extra_json": {
                        "power_capacity_watts": psu.get("PowerCapacityWatts"),
                        "line_input_voltage": psu.get("LineInputVoltage"),
                    },
                }
            )

        processor_models = [component["model"] for component in components if component["component_type"] == "cpu" and component["model"]]
        raid_types = [component["extra_json"].get("raid_type", "") for component in components if component["component_type"] == "virtual_disk"]
        summary_bits = [
            f"CPUs: {len(processors)}",
            f"Memory modules: {len(memory_modules)}",
            f"Physical disks: {len(physical_disks)}",
            f"Virtual disks: {len(virtual_disks)}",
            f"NICs: {len(network_ifaces)}",
            f"PSUs: {len(power_supplies)}",
        ]

        processor_summary = system_data.get("ProcessorSummary")
        processor_vendor = ""
        if isinstance(processor_summary, dict):
            processor_vendor = str(processor_summary.get("Model", "") or processor_summary.get("Status", "") or "")

        disk_total = 0.0
        disk_sources = virtual_disks if virtual_disks else physical_disks
        for entry in disk_sources:
            disk_total += float(_capacity_gb(entry) or 0)

        inventory = {
            "processor_model": ", ".join(sorted(set(processor_models))),
            "processor_vendor": processor_vendor,
            "processor_count": len(processors) or None,
            "physical_cores": sum(int(cpu.get("TotalCores", 0) or 0) for cpu in processors) or None,
            "logical_processors": sum(int(cpu.get("TotalThreads", 0) or 0) for cpu in processors) or None,
            "memory_total_gb": round(sum(float(_capacity_gb(module) or 0) for module in memory_modules), 2) or None,
            "memory_slot_count": len(memory_modules) or None,
            "memory_slots_used": sum(1 for module in memory_modules if (_capacity_gb(module) or 0) > 0) or None,
            "memory_module_count": len(memory_modules) or None,
            "storage_controller_count": len(storage_controllers) or None,
            "physical_disk_count": len(physical_disks) or None,
            "virtual_disk_count": len(virtual_disks) or None,
            "disk_total_gb": round(disk_total, 2) or None,
            "network_interface_count": len(network_ifaces) or None,
            "power_supply_count": len(power_supplies) or None,
            "raid_summary": ", ".join(sorted({item for item in raid_types if item})) or ", ".join(summary_bits),
        }

        health = {
            "overall_status": _rollup_status(
                [
                    _health_value(system_data),
                    _health_value(manager_data),
                    _health_value(chassis_data),
                ]
            )
            or "Unknown",
            "processor_status": _rollup_status([component["health"] or component["status"] for component in components if component["component_type"] == "cpu"]),
            "memory_status": _rollup_status([component["health"] or component["status"] for component in components if component["component_type"] == "memory_module"]),
            "storage_status": _rollup_status(
                [
                    component["health"] or component["status"]
                    for component in components
                    if component["component_type"] in {"raid_controller", "physical_disk", "virtual_disk"}
                ]
            ),
            "power_status": _rollup_status([component["health"] or component["status"] for component in components if component["component_type"] == "power_supply"]),
            "network_status": _rollup_status([component["health"] or component["status"] for component in components if component["component_type"] == "nic"]),
            "thermal_status": _rollup_status([_health_value(temp) or _state_value(temp) for temp in temperatures if isinstance(temp, dict)]),
            "power_state": str(system_data.get("PowerState", "") or ""),
            "alert_count": len(alerts),
            "summary": "; ".join(summary_bits),
        }

        raw_asset = {
            "protocol": "redfish",
            "target_name": target.name,
            "template_key": target.template_key,
            "base_url": base_url,
            "ip_address": host,
            "management_ip": host,
            "service_root": service_root,
            "system": system_data,
            "manager": manager_data,
            "chassis": chassis_data,
            "system_id": str(system_data.get("Id", "") or ""),
            "manager_id": str(manager_data.get("Id", "") or ""),
            "system_name": str(system_data.get("HostName", "") or system_data.get("Name", "") or ""),
            "manager_name": str(manager_data.get("Name", "") or ""),
            "manufacturer": str(system_data.get("Manufacturer", "") or manager_data.get("Manufacturer", "") or ""),
            "model": str(system_data.get("Model", "") or manager_data.get("Model", "") or ""),
            "serial_number": str(system_data.get("SerialNumber", "") or manager_data.get("SerialNumber", "") or ""),
            "firmware_version": str(manager_data.get("FirmwareVersion", "") or system_data.get("BiosVersion", "") or ""),
            "power_state": str(system_data.get("PowerState", "") or ""),
            "health": str(
                (
                    system_data.get("Status", {}) if isinstance(system_data.get("Status"), dict) else {}
                ).get("Health", "")
                or (
                    manager_data.get("Status", {}) if isinstance(manager_data.get("Status"), dict) else {}
                ).get("Health", "")
            ),
            "inventory": inventory,
            "components": components,
            "health_summary": health,
            "alerts": alerts,
        }
        return [raw_asset]
    finally:
        session.close()
