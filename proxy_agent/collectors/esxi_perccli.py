"""Collect ESXi RAID inventory via PERCCLI over SSH."""
from __future__ import annotations

import json
import re
from typing import Any

import paramiko


def _load_json(text: str) -> dict[str, Any]:
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_controller(payload: dict[str, Any]) -> dict[str, Any]:
    controllers = payload.get("Controllers")
    if not isinstance(controllers, list) or not controllers:
        return {}
    first = controllers[0]
    return first if isinstance(first, dict) else {}


def _response_data(payload: dict[str, Any]) -> dict[str, Any]:
    controller = _first_controller(payload)
    data = controller.get("Response Data")
    return data if isinstance(data, dict) else {}


def _command_status(payload: dict[str, Any]) -> dict[str, Any]:
    controller = _first_controller(payload)
    data = controller.get("Command Status")
    return data if isinstance(data, dict) else {}


def _parse_size_gb(text: Any) -> float | None:
    value = str(text or "").strip()
    if not value:
        return None
    match = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*(KB|MB|GB|TB)", value, re.IGNORECASE)
    if not match:
        return None
    amount = float(match.group(1))
    unit = match.group(2).upper()
    if unit == "KB":
        return round(amount / (1024 ** 2), 2)
    if unit == "MB":
        return round(amount / 1024, 2)
    if unit == "GB":
        return round(amount, 2)
    if unit == "TB":
        return round(amount * 1024, 2)
    return None


def _parse_eid_slot(value: Any) -> tuple[str, str]:
    text = str(value or "").strip()
    if ":" not in text:
        return "", text
    enclosure, slot = text.split(":", 1)
    return enclosure.strip(), slot.strip()


def _is_problem_state(value: Any) -> bool:
    state = str(value or "").strip().lower()
    return bool(state) and state not in {"onln", "optl", "ok", "ugood"}


def _run_command(client: paramiko.SSHClient, command: str, timeout_s: float) -> tuple[int, str, str]:
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout_s)
    _ = stdin
    out = stdout.read().decode("utf-8", errors="ignore")
    err = stderr.read().decode("utf-8", errors="ignore")
    exit_status = stdout.channel.recv_exit_status()
    return exit_status, out, err


def collect_esxi_perccli(
    host: str,
    username: str,
    password: str,
    perccli_path: str = "/opt/lsi/perccli/perccli",
    controller_index: int = 0,
    timeout_s: float = 20.0,
) -> dict[str, Any]:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout_s,
        banner_timeout=timeout_s,
        auth_timeout=timeout_s,
    )
    try:
        ctl_code, ctl_out, ctl_err = _run_command(client, f"{perccli_path} /c{controller_index} show J", timeout_s)
        pd_code, pd_out, pd_err = _run_command(client, f"{perccli_path} /c{controller_index} /eall /sall show all J", timeout_s)
        vd_code, vd_out, vd_err = _run_command(client, f"{perccli_path} /c{controller_index} /vall show all J", timeout_s)
    finally:
        client.close()

    controller_payload = _load_json(ctl_out)
    physical_payload = _load_json(pd_out)
    virtual_payload = _load_json(vd_out)

    controller_data = _response_data(controller_payload)
    physical_data = _response_data(physical_payload)
    virtual_data = _response_data(virtual_payload)

    controller = {
        "controller_index": controller_index,
        "product_name": str(controller_data.get("Product Name", "") or "").strip(),
        "serial_number": str(controller_data.get("Serial Number", "") or "").strip(),
        "sas_address": str(controller_data.get("SAS Address", "") or "").strip(),
        "pci_address": str(controller_data.get("PCI Address", "") or "").strip(),
        "firmware_package": str(controller_data.get("FW Package Build", "") or "").strip(),
        "firmware_version": str(controller_data.get("FW Version", "") or "").strip(),
        "bios_version": str(controller_data.get("BIOS Version", "") or "").strip(),
        "driver_name": str(controller_data.get("Driver Name", "") or "").strip(),
        "driver_version": str(controller_data.get("Driver Version", "") or "").strip(),
        "health": str(controller_data.get("Status", "") or "").strip(),
        "drive_groups": controller_data.get("Drive Groups"),
        "physical_drives": controller_data.get("Physical Drives"),
        "virtual_drives": controller_data.get("Virtual Drives"),
    }

    physical_disks = []
    pd_list = controller_data.get("PD LIST")
    if isinstance(pd_list, list):
        for entry in pd_list:
            if not isinstance(entry, dict):
                continue
            enclosure_id, slot = _parse_eid_slot(entry.get("EID:Slt"))
            physical_disks.append(
                {
                    "enclosure_id": enclosure_id,
                    "slot": slot,
                    "state": str(entry.get("State", "") or "").strip(),
                    "drive_group": str(entry.get("DG", "") or "").strip(),
                    "size_text": str(entry.get("Size", "") or "").strip(),
                    "size_gb": _parse_size_gb(entry.get("Size")),
                    "interface": str(entry.get("Intf", "") or "").strip(),
                    "media": str(entry.get("Med", "") or "").strip(),
                    "sector_size": str(entry.get("SeSz", "") or "").strip(),
                    "model": str(entry.get("Model", "") or "").strip(),
                    "device_id": str(entry.get("DID", "") or "").strip(),
                    "spin_state": str(entry.get("Sp", "") or "").strip(),
                }
            )

    detailed_disks: dict[str, dict[str, Any]] = {}
    for key, value in physical_data.items():
        if not isinstance(key, str) or not key.startswith("Drive /c"):
            continue
        if not isinstance(value, dict):
            continue
        match = re.search(r"/e([0-9]+)/s([0-9]+)", key)
        if not match:
            continue
        disk_key = f"{match.group(1)}:{match.group(2)}"
        detailed_disks[disk_key] = value

    for disk in physical_disks:
        detail = detailed_disks.get(f"{disk['enclosure_id']}:{disk['slot']}", {})
        attrs = detail.get(f"Drive /c{controller_index}/e{disk['enclosure_id']}/s{disk['slot']} Device attributes")
        if isinstance(attrs, dict):
            disk["serial_number"] = str(attrs.get("SN", "") or "").strip()
            disk["firmware_revision"] = str(attrs.get("Firmware Revision", "") or "").strip()
            disk["wwn"] = str(attrs.get("WWN", "") or "").strip()
            disk["raw_size"] = str(attrs.get("Raw size", "") or "").strip()
        policies = detail.get(f"Drive /c{controller_index}/e{disk['enclosure_id']}/s{disk['slot']} Policies/Settings")
        if isinstance(policies, dict):
            disk["drive_position"] = str(policies.get("Drive position", "") or "").strip()
            disk["connected_port"] = str(policies.get("Connected Port Number", "") or "").strip()
        if _is_problem_state(disk.get("state")) and disk["enclosure_id"] and disk["slot"]:
            query = f"{perccli_path} /c{controller_index}/e{disk['enclosure_id']}/s{disk['slot']} show J"
            query_code, query_out, query_err = _run_command(client, query, timeout_s)
            query_payload = _load_json(query_out)
            query_status = _command_status(query_payload)
            query_data = _response_data(query_payload)
            if query_status:
                disk["query_command_status"] = query_status
            if query_data:
                disk["query_response_data"] = query_data
            if query_code:
                disk["query_exit_code"] = query_code
            if query_err.strip():
                disk["query_stderr"] = query_err.strip()

    virtual_disks = []
    for key, value in virtual_data.items():
        if not isinstance(key, str) or not key.startswith("/c"):
            continue
        if not isinstance(value, list) or not value:
            continue
        first = value[0]
        if not isinstance(first, dict):
            continue
        vd_match = re.search(r"/v([0-9]+)", key)
        vd_index = vd_match.group(1) if vd_match else ""
        props = virtual_data.get(f"VD{vd_index} Properties")
        props = props if isinstance(props, dict) else {}
        pds = virtual_data.get(f"PDs for VD {vd_index}")
        members = pds if isinstance(pds, list) else []
        member_slots = [str(item.get("EID:Slt", "") or "").strip() for item in members if isinstance(item, dict)]
        virtual_disks.append(
            {
                "virtual_disk": vd_index,
                "drive_group": str(first.get("DG/VD", "") or "").split("/", 1)[0],
                "raid_type": str(first.get("TYPE", "") or "").strip(),
                "state": str(first.get("State", "") or "").strip(),
                "size_gb": _parse_size_gb(first.get("Size")),
                "access": str(first.get("Access", "") or "").strip(),
                "cache": str(first.get("Cache", "") or "").strip(),
                "strip_size": str(props.get("Strip Size", "") or "").strip(),
                "drives_per_span": props.get("Number of Drives Per Span"),
                "span_depth": props.get("Span Depth"),
                "naa_id": str(props.get("SCSI NAA Id", "") or "").strip(),
                "member_slots": member_slots,
            }
        )

    enclosures = []
    enclosure_list = controller_data.get("Enclosure LIST")
    if isinstance(enclosure_list, list):
        for entry in enclosure_list:
            if not isinstance(entry, dict):
                continue
            enclosures.append(
                {
                    "enclosure_id": str(entry.get("EID", "") or "").strip(),
                    "state": str(entry.get("State", "") or "").strip(),
                    "slots": entry.get("Slots"),
                    "physical_drive_count": entry.get("PD"),
                    "product_id": str(entry.get("ProdID", "") or "").strip(),
                    "vendor_specific": str(entry.get("VendorSpecific", "") or "").strip(),
                }
            )

    return {
        "controller": controller,
        "physical_disks": physical_disks,
        "virtual_disks": virtual_disks,
        "enclosures": enclosures,
        "command_status": {
            "controller": _command_status(controller_payload),
            "physical_disks": _command_status(physical_payload),
            "virtual_disks": _command_status(virtual_payload),
            "exit_codes": {
                "controller": ctl_code,
                "physical_disks": pd_code,
                "virtual_disks": vd_code,
            },
            "stderr": {
                "controller": ctl_err.strip(),
                "physical_disks": pd_err.strip(),
                "virtual_disks": vd_err.strip(),
            },
        },
    }
