"""Fallback generic SNMP device template."""
from __future__ import annotations

from typing import Any

from proxy_agent.templates.base import DeviceTemplate


def infer_vendor(text: str) -> str:
    haystack = text.lower()
    if "cisco" in haystack:
        return "Cisco"
    if "dell" in haystack:
        return "Dell"
    if "avaya" in haystack:
        return "Avaya"
    if "hewlett" in haystack or "aruba" in haystack or "procurve" in haystack or " hp " in f" {haystack} ":
        return "HPE"
    if "juniper" in haystack:
        return "Juniper"
    return ""


class GenericSnmpTemplate(DeviceTemplate):
    key = "generic_snmp"
    display_name = "Generic SNMP Device"
    supported_protocols = ["snmp"]

    def match(self, raw_facts: dict[str, Any]) -> bool:
        return str(raw_facts.get("protocol", "")).lower() == "snmp"

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        combined = " ".join(
            [
                str(raw_facts.get("sys_descr", "") or ""),
                str(raw_facts.get("sys_name", "") or ""),
                str(raw_facts.get("model", "") or ""),
            ]
        )
        vendor = infer_vendor(combined)
        display_name = (
            str(raw_facts.get("sys_name", "") or "").strip()
            or str(raw_facts.get("model", "") or "").strip()
            or str(raw_facts.get("management_ip", "") or "").strip()
        )
        return {
            "asset_class": "network",
            "display_name": display_name or "SNMP device",
            "vendor": vendor,
            "model": str(raw_facts.get("model", "") or ""),
            "serial_number": str(raw_facts.get("serial_number", "") or ""),
            "firmware_version": str(raw_facts.get("firmware_version", "") or ""),
            "ip_address": str(raw_facts.get("ip_address", "") or ""),
            "management_ip": str(raw_facts.get("management_ip", "") or ""),
            "mac_address": str(raw_facts.get("mac_address", "") or ""),
            "status": "Discovered",
            "raw_facts": self.build_raw_facts(raw_facts),
        }
