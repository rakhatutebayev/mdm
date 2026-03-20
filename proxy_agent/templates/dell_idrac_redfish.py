"""Dell iDRAC template for Redfish-collected assets."""
from __future__ import annotations

from typing import Any

from proxy_agent.templates.base import DeviceTemplate


class DellIdracRedfishTemplate(DeviceTemplate):
    key = "dell_idrac_redfish"
    display_name = "Dell iDRAC Redfish"
    supported_protocols = ["redfish"]

    def match(self, raw_facts: dict[str, Any]) -> bool:
        if str(raw_facts.get("protocol", "")).lower() != "redfish":
            return False
        combined = " ".join(
            [
                str(raw_facts.get("manufacturer", "") or ""),
                str(raw_facts.get("model", "") or ""),
                str(raw_facts.get("manager_name", "") or ""),
                str(raw_facts.get("system_name", "") or ""),
            ]
        ).lower()
        return "dell" in combined or "idrac" in combined

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        model = str(raw_facts.get("model", "") or "").strip() or "iDRAC"
        display_name = (
            str(raw_facts.get("manager_name", "") or "").strip()
            or str(raw_facts.get("system_name", "") or "").strip()
            or f"Dell {model}"
        )
        health = str(raw_facts.get("health", "") or "").strip()
        health_summary = raw_facts.get("health_summary")
        if not isinstance(health_summary, dict):
            health_summary = {}
        overall_status = str(health_summary.get("overall_status", "") or health).strip()
        status = (
            f"Healthy ({overall_status})"
            if overall_status and overall_status.lower() not in {"ok", "healthy"}
            else (overall_status or "Discovered")
        )
        return {
            "asset_class": "idrac",
            "display_name": display_name,
            "vendor": "Dell",
            "model": model,
            "serial_number": str(raw_facts.get("serial_number", "") or ""),
            "firmware_version": str(raw_facts.get("firmware_version", "") or ""),
            "ip_address": str(raw_facts.get("ip_address", "") or ""),
            "management_ip": str(raw_facts.get("management_ip", "") or ""),
            "mac_address": "",
            "status": status,
            "inventory": raw_facts.get("inventory") if isinstance(raw_facts.get("inventory"), dict) else None,
            "components": raw_facts.get("components") if isinstance(raw_facts.get("components"), list) else [],
            "health": health_summary or None,
            "alerts": raw_facts.get("alerts") if isinstance(raw_facts.get("alerts"), list) else [],
            "raw_facts": self.build_raw_facts(
                raw_facts,
                {
                    "vendor": "Dell",
                    "power_state": str(raw_facts.get("power_state", "") or ""),
                    "health": health,
                },
            ),
        }
