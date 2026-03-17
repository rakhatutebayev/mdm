from __future__ import annotations

import os
import platform
import socket
import time
import uuid
from typing import Any

import psutil

try:
    import pythoncom  # type: ignore[import-not-found]
except ImportError:
    pythoncom = None

try:
    import wmi  # type: ignore[import-not-found]
except ImportError:
    wmi = None


# Connection type codes from WmiMonitorConnectionParams.VideoOutputTechnology
_CONN_TYPE_MAP = {
    -2147483648: "Uninitialized", -1: "Unknown", 0: "VGA", 1: "S-Video",
    2: "Composite", 3: "Component", 4: "DVI", 5: "HDMI", 6: "LVDS",
    8: "D-Jpn", 9: "SDI", 10: "DisplayPort", 11: "UDI", 16: "Internal (laptop)",
}


def _wmi_str_from_bytes(byte_array) -> str:
    """Convert WMI byte array (list of ints) to a clean ASCII string."""
    try:
        return bytes(b for b in byte_array if b).decode("ascii", errors="replace").strip()
    except Exception:
        return ""


def _parse_edid(edid: bytes) -> dict:
    """Parse EDID binary blob → manufacturer, model, serial, size_inches."""
    result = {"manufacturer": "", "model": "", "serial_number": "", "display_size": ""}
    if len(edid) < 128:
        return result

    # Manufacturer ID — 3 letters packed into 2 bytes at offset 8-9
    mid = (edid[8] << 8) | edid[9]
    c1 = ((mid >> 10) & 0x1F) + 64
    c2 = ((mid >> 5)  & 0x1F) + 64
    c3 = (mid         & 0x1F) + 64
    mfr_id = chr(c1) + chr(c2) + chr(c3)
    # Expand well-known IDs
    _KNOWN = {
        "SAM": "Samsung", "DEL": "Dell", "LEN": "Lenovo", "BNQ": "BenQ",
        "AOC": "AOC", "ACI": "Asus", "GBR": "LG", "GSM": "LG", "HWP": "HP",
        "PHL": "Philips", "ACR": "Acer", "NEC": "NEC", "CMO": "Innolux",
        "CMN": "Innolux", "BOE": "BOE", "AUO": "AU Optronics",
    }
    result["manufacturer"] = _KNOWN.get(mfr_id, mfr_id)

    # Physical size at 21-22 (cm)
    w_cm, h_cm = edid[21], edid[22]
    if w_cm and h_cm:
        import math
        diag = round(math.sqrt(w_cm**2 + h_cm**2) / 2.54, 1)
        result["display_size"] = f'{diag}"'

    # Descriptor blocks at 54, 72, 90, 108 — look for model (0xFC) and serial (0xFF)
    for offset in (54, 72, 90, 108):
        if len(edid) < offset + 18:
            break
        hdr = edid[offset:offset + 3]
        block_type = edid[offset + 3]
        text = edid[offset + 5:offset + 18].decode("cp437", errors="replace").rstrip()
        text = text.replace("\n", "").strip()
        if block_type == 0xFC:   # Monitor name
            result["model"] = text
        elif block_type == 0xFF: # Serial number string
            result["serial_number"] = text

    return result


def _collect_monitors() -> list[dict]:
    """Collect monitor info from Windows registry EDID — works in Service Session 0.

    Reads EDID from HKLM\\SYSTEM\\CurrentControlSet\\Enum\\DISPLAY\\*\\*\\Device Parameters
    and parses manufacturer code, model name, serial, physical size. Falls back to
    empty list on non-Windows or VMs with no monitor registry entries.
    """
    if os.name != "nt":
        return []

    monitors: list[dict] = []
    try:
        import winreg  # only available on Windows

        # Get resolution from Win32_VideoController (accessible from SYSTEM)
        vc_resolutions: list[str] = []
        try:
            if wmi:
                c = wmi.WMI()
                for vc in c.Win32_VideoController():
                    w = getattr(vc, "CurrentHorizontalResolution", None)
                    h = getattr(vc, "CurrentVerticalResolution", None)
                    if w and h:
                        vc_resolutions.append(f"{w}x{h}")
        except Exception:
            pass

        # Walk DISPLAY registry tree for EDID data
        enum_path = r"SYSTEM\CurrentControlSet\Enum\DISPLAY"
        try:
            enum_key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, enum_path)
        except OSError:
            return []

        idx = 0
        mon_idx = 0
        while True:
            try:
                vendor_name = winreg.EnumKey(enum_key, idx)
                idx += 1
            except OSError:
                break

            vendor_key = winreg.OpenKey(enum_key, vendor_name)
            sub_idx = 0
            while True:
                try:
                    instance_name = winreg.EnumKey(vendor_key, sub_idx)
                    sub_idx += 1
                except OSError:
                    break

                try:
                    params_path = f"{vendor_name}\\{instance_name}\\Device Parameters"
                    params_key = winreg.OpenKey(enum_key, params_path)
                    edid_data, _ = winreg.QueryValueEx(params_key, "EDID")
                    winreg.CloseKey(params_key)

                    parsed = _parse_edid(bytes(edid_data))
                    # Skip generic/empty entries (e.g. headless VMs return blank EDID)
                    if not parsed["manufacturer"] and not parsed["model"]:
                        continue

                    resolution = (vc_resolutions[mon_idx]
                                  if mon_idx < len(vc_resolutions)
                                  else (vc_resolutions[0] if vc_resolutions else ""))
                    monitors.append({
                        "display_index":   mon_idx + 1,
                        "manufacturer":    parsed["manufacturer"],
                        "model":           parsed["model"],
                        "serial_number":   parsed["serial_number"],
                        "display_size":    parsed["display_size"],
                        "resolution":      resolution,
                        "connection_type": "",
                        "refresh_rate":    "",
                        "color_depth":     "",
                        "hdr_support":     False,
                    })
                    mon_idx += 1
                except (OSError, KeyError):
                    pass

            winreg.CloseKey(vendor_key)

        winreg.CloseKey(enum_key)
    except Exception:
        pass

    return monitors


def _get_os_version() -> str:
    """Return a clean OS version string. Correctly distinguishes Windows 10 vs 11."""
    import platform as _platform
    if os.name != "nt":
        return _platform.platform()

    try:
        build = int(_platform.version().split(".")[-1])
        win_version = "Windows 11" if build >= 22000 else "Windows 10"

        # Try to get edition (Pro/Home/Enterprise) from registry
        edition = ""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                 r"SOFTWARE\Microsoft\Windows NT\CurrentVersion")
            edition, _ = winreg.QueryValueEx(key, "EditionID")
            winreg.CloseKey(key)
        except Exception:
            pass

        if edition:
            return f"{win_version} {edition} (Build {build})"
        return f"{win_version} (Build {build})"
    except Exception:
        import platform as _platform
        return _platform.platform()


def _safe(callable_obj, fallback: Any = "") -> Any:
    try:
        return callable_obj()
    except Exception:
        return fallback


def _first_ipv4() -> str:
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if entry.family == socket.AF_INET and not entry.address.startswith("127."):
                return entry.address
    return ""


def _first_mac() -> str:
    for entries in psutil.net_if_addrs().values():
        for entry in entries:
            if getattr(psutil, "AF_LINK", object()) == entry.family and entry.address:
                return entry.address
    return ""


def _to_gb(value: Any) -> float | None:
    try:
        return round(int(value) / (1024 ** 3), 2)
    except Exception:
        return None


def _machine_class(manufacturer: str, model: str) -> str:
    marker = f"{manufacturer} {model}".lower()
    virtual_markers = (
        "virtual",
        "vmware",
        "virtualbox",
        "kvm",
        "qemu",
        "hyper-v",
        "xen",
        "parallels",
    )
    return "Virtual Machine" if any(token in marker for token in virtual_markers) else "Physical Machine"


def _chassis_type(chassis_codes: list[int], machine_class: str) -> str:
    if machine_class == "Virtual Machine":
        return "Virtual Machine"

    laptop_codes = {8, 9, 10, 14, 30, 31, 32}
    desktop_codes = {3, 4, 5, 6, 7, 13, 15, 16}
    server_codes = {17, 23, 28}

    if any(code in laptop_codes for code in chassis_codes):
        return "Laptop"
    if any(code in server_codes for code in chassis_codes):
        return "Server"
    if any(code in desktop_codes for code in chassis_codes):
        return "Desktop"
    return "Desktop" if os.name == "nt" else "Unknown"


def _drive_type_name(code: Any) -> str:
    return {
        0: "Unknown",
        1: "No Root Directory",
        2: "Removable",
        3: "Local Disk",
        4: "Network",
        5: "CD-ROM",
        6: "RAM Disk",
    }.get(int(code), "Unknown")


def _logical_disk_telemetry() -> list[dict[str, Any]]:
    disks: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        mount = part.mountpoint
        device_name = part.device or mount
        if os.name == "nt" and not device_name:
            continue
        try:
            usage = psutil.disk_usage(mount)
        except Exception:
            continue
        disks.append({
            "name": str(device_name).strip(),
            "volume_name": "",
            "file_system": part.fstype or "",
            "drive_type": "Local Disk",
            "size_gb": round(usage.total / (1024 ** 3), 2),
            "free_gb": round(usage.free / (1024 ** 3), 2),
            "used_gb": round(usage.used / (1024 ** 3), 2),
        })
    return disks


def _collect_windows_inventory() -> dict[str, Any]:
    if os.name != "nt" or wmi is None:
        return {}

    initialized = False
    if pythoncom is not None:
        try:
            pythoncom.CoInitialize()
            initialized = True
        except Exception:
            initialized = False

    try:
        client = wmi.WMI()
        computer = client.Win32_ComputerSystem()[0] if client.Win32_ComputerSystem() else None
        bios = client.Win32_BIOS()[0] if client.Win32_BIOS() else None
        enclosure = client.Win32_SystemEnclosure()[0] if client.Win32_SystemEnclosure() else None
        processors = client.Win32_Processor()
        memory_modules = client.Win32_PhysicalMemory()
        memory_arrays = client.Win32_PhysicalMemoryArray()
        physical_disks = client.Win32_DiskDrive()
        logical_disks = client.Win32_LogicalDisk()

        manufacturer = str(getattr(computer, "Manufacturer", "") or "")
        model = str(getattr(computer, "Model", "") or "")
        machine_class = _machine_class(manufacturer, model)
        chassis_codes = [int(code) for code in (getattr(enclosure, "ChassisTypes", None) or []) if str(code).isdigit()]
        chassis_type = _chassis_type(chassis_codes, machine_class)

        processor_model = ""
        processor_vendor = ""
        physical_cores = None
        logical_processors = None
        if processors:
            processor_model = str(getattr(processors[0], "Name", "") or "").strip()
            processor_vendor = str(getattr(processors[0], "Manufacturer", "") or "").strip()
            physical_cores = sum(int(getattr(cpu, "NumberOfCores", 0) or 0) for cpu in processors) or None
            logical_processors = sum(int(getattr(cpu, "NumberOfLogicalProcessors", 0) or 0) for cpu in processors) or None

        slot_count = sum(int(getattr(arr, "MemoryDevices", 0) or 0) for arr in memory_arrays) or None
        slots_used = sum(1 for module in memory_modules if int(getattr(module, "Capacity", 0) or 0) > 0) or None

        hardware_inventory = {
            "processor_model": processor_model,
            "processor_vendor": processor_vendor,
            "physical_cores": physical_cores,
            "logical_processors": logical_processors,
            "memory_total_gb": _to_gb(getattr(computer, "TotalPhysicalMemory", 0)),
            "memory_slot_count": slot_count,
            "memory_slots_used": slots_used,
            "memory_module_count": len(memory_modules) or None,
            "machine_class": machine_class,
            "chassis_type": chassis_type,
        }

        physical_disk_items = []
        for disk in physical_disks:
            physical_disk_items.append({
                "disk_index": int(getattr(disk, "Index", 0)) if str(getattr(disk, "Index", "")).isdigit() else None,
                "model": str(getattr(disk, "Model", "") or "").strip(),
                "serial_number": str(getattr(disk, "SerialNumber", "") or "").strip(),
                "media_type": str(getattr(disk, "MediaType", "") or "").strip(),
                "interface_type": str(getattr(disk, "InterfaceType", "") or "").strip(),
                "size_gb": _to_gb(getattr(disk, "Size", 0)),
            })

        logical_disk_items = []
        for disk in logical_disks:
            size_gb = _to_gb(getattr(disk, "Size", 0))
            free_gb = _to_gb(getattr(disk, "FreeSpace", 0))
            used_gb = round(size_gb - free_gb, 2) if size_gb is not None and free_gb is not None else None
            logical_disk_items.append({
                "name": str(getattr(disk, "DeviceID", "") or "").strip(),
                "volume_name": str(getattr(disk, "VolumeName", "") or "").strip(),
                "file_system": str(getattr(disk, "FileSystem", "") or "").strip(),
                "drive_type": _drive_type_name(getattr(disk, "DriveType", 0)),
                "size_gb": size_gb,
                "free_gb": free_gb,
                "used_gb": used_gb,
            })

        return {
            "device_type": chassis_type,
            "manufacturer": manufacturer,
            "model": model,
            "serial_number": str(getattr(bios, "SerialNumber", "") or "").strip(),
            "hardware_inventory": hardware_inventory,
            "physical_disks": physical_disk_items,
            "logical_disks": logical_disk_items,
        }
    except Exception:
        return {}
    finally:
        if initialized and pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _identity_payload(config) -> dict[str, Any]:
    windows_inventory = _collect_windows_inventory()
    return {
        "device_name": socket.gethostname(),
        "platform": "Windows" if os.name == "nt" else platform.system(),
        "device_type": windows_inventory.get("device_type") or "Desktop",
        "model": windows_inventory.get("model") or platform.machine(),
        "manufacturer": windows_inventory.get("manufacturer") or platform.node(),
        "serial_number": windows_inventory.get("serial_number") or "",
        "udid": hex(uuid.getnode())[2:].upper(),
        "os_version": _get_os_version(),
        "architecture": platform.machine(),
        "owner": os.getenv("USERNAME", ""),
        "enrollment_method": "WindowsService",
        "agent_version": config.agent_version,
        "hardware_inventory": windows_inventory.get("hardware_inventory"),
        "physical_disks": windows_inventory.get("physical_disks", []),
        "logical_disks": windows_inventory.get("logical_disks", []),
    }


def _network_payload() -> dict[str, Any]:
    return {
        "network": {
            "ip_address": _first_ipv4(),
            "mac_address": _first_mac(),
            "hostname": socket.gethostname(),
            "wifi_ssid": "",
            "connection_type": "Ethernet",
            "dns_server": "",
            "default_gateway": "",
        },
    }


def collect_enrollment_payload(config) -> dict[str, Any]:
    return {
        "customer_id": config.customer_id,
        "enrollment_token": config.enrollment_token,
        **_identity_payload(config),
        **_network_payload(),
        "monitors": _collect_monitors(),
    }


def collect_heartbeat_payload(config) -> dict[str, Any]:
    return {
        "device_id": config.device_id,
        "agent_version": config.agent_version,
        "os_version": _get_os_version(),
        "ip_address": _first_ipv4(),
    }


def collect_metrics_payload(config) -> dict[str, Any]:
    vm = _safe(psutil.virtual_memory)
    disk = _safe(lambda: psutil.disk_usage("C:\\" if os.name == "nt" else "/"))
    boot_time = _safe(psutil.boot_time, 0.0)
    logical_disks = _logical_disk_telemetry()

    return {
        **collect_heartbeat_payload(config),
        "cpu_pct": _safe(lambda: round(psutil.cpu_percent(interval=1), 1), None),
        "ram_used_gb": _safe(lambda: round((vm.used / (1024 ** 3)), 2), None) if vm else None,
        "ram_total_gb": _safe(lambda: round((vm.total / (1024 ** 3)), 2), None) if vm else None,
        "disk_used_gb": _safe(lambda: round((disk.used / (1024 ** 3)), 2), None) if disk else None,
        "disk_total_gb": _safe(lambda: round((disk.total / (1024 ** 3)), 2), None) if disk else None,
        "uptime_seconds": _safe(lambda: max(0, int(time.time() - boot_time)), 0),
        "logical_disks": logical_disks,
    }


def collect_inventory_payload(config) -> dict[str, Any]:
    return {
        "device_id": config.device_id,
        **_identity_payload(config),
        **_network_payload(),
        "monitors": _collect_monitors(),
    }
