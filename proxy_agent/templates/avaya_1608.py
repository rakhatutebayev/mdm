"""Avaya 1608 device template."""
from __future__ import annotations

from typing import Any

from proxy_agent.templates.base import DeviceTemplate


class Avaya1608Template(DeviceTemplate):
    key = "avaya_1608"
    display_name = "Avaya 1608"
    supported_protocols = ["snmp"]

    def match(self, raw_facts: dict[str, Any]) -> bool:
        combined = " ".join(
            [
                str(raw_facts.get("sys_descr", "") or ""),
                str(raw_facts.get("sys_name", "") or ""),
                str(raw_facts.get("model", "") or ""),
            ]
        ).lower()
        return "avaya" in combined and "1608" in combined

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        avaya_details = raw_facts.get("avaya_details")
        if not isinstance(avaya_details, dict):
            avaya_details = {}

        model = (
            str(raw_facts.get("model", "") or "").strip()
            or str(avaya_details.get("model", "") or "").strip()
            or "1608"
        )
        serial_number = (
            str(raw_facts.get("serial_number", "") or "").strip()
            or str(avaya_details.get("serial_number", "") or "").strip()
            or str(avaya_details.get("serial_number_alt", "") or "").strip()
        )
        firmware_version = (
            str(raw_facts.get("firmware_version", "") or "").strip()
            or str(avaya_details.get("firmware_version", "") or "").strip()
        )
        mac_address = (
            str(raw_facts.get("mac_address", "") or "").strip()
            or str(avaya_details.get("mac_address", "") or "").strip()
        )
        display_name = (
            str(raw_facts.get("sys_name", "") or "").strip()
            or f"Avaya {model}"
        )
        return {
            "asset_class": "voip",
            "display_name": display_name,
            "vendor": "Avaya",
            "model": model,
            "serial_number": serial_number,
            "firmware_version": firmware_version,
            "ip_address": str(raw_facts.get("ip_address", "") or ""),
            "management_ip": str(raw_facts.get("management_ip", "") or ""),
            "mac_address": mac_address,
            "status": "Discovered",
            "raw_facts": self.build_raw_facts(
                raw_facts,
                {
                    "vendor": "Avaya",
                    "extension": str(avaya_details.get("extension", "") or ""),
                    "phone_number": str(avaya_details.get("phone_number", "") or ""),
                },
            ),
        }
