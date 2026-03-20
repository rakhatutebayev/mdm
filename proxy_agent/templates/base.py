"""Base device template contract for Proxy Agent."""
from __future__ import annotations

from typing import Any


class DeviceTemplate:
    key = "base"
    display_name = "Base Template"
    supported_protocols: list[str] = []

    def match(self, raw_facts: dict[str, Any]) -> bool:
        return False

    def normalize(self, raw_facts: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def identity(self, raw_facts: dict[str, Any]) -> dict[str, str]:
        return {
            "serial_number": str(raw_facts.get("serial_number", "") or ""),
            "management_ip": str(raw_facts.get("management_ip", "") or ""),
            "mac_address": str(raw_facts.get("mac_address", "") or ""),
        }

    def build_raw_facts(self, raw_facts: dict[str, Any], extra: dict[str, Any] | None = None) -> dict[str, Any]:
        payload = dict(raw_facts)
        payload["template_key"] = self.key
        payload["template_name"] = self.display_name
        if extra:
            payload.update(extra)
        return payload
