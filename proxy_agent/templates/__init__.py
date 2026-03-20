"""Device template registry for Proxy Agent."""

from __future__ import annotations

from proxy_agent.templates.base import DeviceTemplate
from proxy_agent.templates.avaya_1608 import Avaya1608Template
from proxy_agent.templates.dell_idrac import DellIdracTemplate
from proxy_agent.templates.dell_idrac_redfish import DellIdracRedfishTemplate
from proxy_agent.templates.generic_snmp import GenericSnmpTemplate
from proxy_agent.templates.switch_generic import GenericSwitchTemplate
from proxy_agent.templates.vmware_esxi import VmwareEsxiTemplate


TEMPLATES: list[DeviceTemplate] = [
    DellIdracRedfishTemplate(),
    Avaya1608Template(),
    DellIdracTemplate(),
    VmwareEsxiTemplate(),
    GenericSwitchTemplate(),
    GenericSnmpTemplate(),
]


def get_template_by_key(key: str) -> DeviceTemplate | None:
    lookup = (key or "").strip().lower()
    if not lookup:
        return None
    for template in TEMPLATES:
        if template.key == lookup:
            return template
    return None


def resolve_template(raw_facts: dict) -> DeviceTemplate:
    explicit = get_template_by_key(str(raw_facts.get("template_key", "")))
    if explicit:
        return explicit

    for template in TEMPLATES:
        if template.match(raw_facts):
            return template

    return GenericSnmpTemplate()
