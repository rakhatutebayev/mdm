"""Generic switch template."""
from __future__ import annotations

from typing import Any

from proxy_agent.templates.base import DeviceTemplate


def infer_switch_vendor(text: str) -> str:
    haystack = text.lower()
    if "cisco" in haystack:
        return "Cisco"
    if "aruba" in haystack or "procurve" in haystack or "hewlett" in haystack:
        return "HPE"
    if "juniper" in haystack:
        return "Juniper"
    if "dell" in haystack:
        return "Dell"
    return ""


class GenericSwitchTemplate(DeviceTemplate):
    key = "switch_generic"
    display_name = "Generic Switch"
    supported_protocols = ["snmp", "lldp"]

    def match(self, raw_facts: dict[str, Any]) -> bool:
        combined = " ".join(
            [
                str(raw_facts.get("sys_descr", "") or ""),
                str(raw_facts.get("sys_name", "") or ""),
                str(raw_facts.get("model", "") or ""),
            ]
        ).lower()
        return "switch" in combined

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        combined = " ".join(
            [
                str(raw_facts.get("sys_descr", "") or ""),
                str(raw_facts.get("sys_name", "") or ""),
                str(raw_facts.get("model", "") or ""),
            ]
        )
        vendor = infer_switch_vendor(combined)
        display_name = (
            str(raw_facts.get("sys_name", "") or "").strip()
            or str(raw_facts.get("model", "") or "").strip()
            or str(raw_facts.get("management_ip", "") or "").strip()
        )
        return {
            "asset_class": "switch",
            "display_name": display_name or "Network switch",
            "vendor": vendor,
            "model": str(raw_facts.get("model", "") or ""),
            "serial_number": str(raw_facts.get("serial_number", "") or ""),
            "firmware_version": str(raw_facts.get("firmware_version", "") or ""),
            "ip_address": str(raw_facts.get("ip_address", "") or ""),
            "management_ip": str(raw_facts.get("management_ip", "") or ""),
            "mac_address": str(raw_facts.get("mac_address", "") or ""),
            "status": "Discovered",
            "raw_facts": self.build_raw_facts(raw_facts, {"vendor": vendor}),
        }
