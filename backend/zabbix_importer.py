"""
zabbix_importer.py
──────────────────
Parses Zabbix template files (XML, JSON, YAML) and converts them to
NOCKO SNMP profile/template/item structure.

Supported formats:
  • XML  (.xml)  — Zabbix 1.x – 6.x
  • JSON (.json) — Zabbix 4.x+
  • YAML (.yaml / .yml) — Zabbix 6.x+

Output schema (matches CreateProfileRequest + CreateTemplateRequest + CreateItemRequest):
  {
    "profile": { name, vendor, version, description },
    "templates": [
      {
        "name": str,
        "description": str,
        "items": [
          { key, name, value_type, poll_class, interval_sec }
        ]
      }
    ],
    "warnings": [...str]
  }
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ─── Zabbix value type → NOCKO value_type ─────────────────────────────────────
# Zabbix types: 0=numeric_float, 3=numeric_uint, 1=character, 2=log, 4=text
_ZBXTYPE_MAP: dict[str, str] = {
    "0": "float",
    "3": "uint",
    "1": "string",
    "2": "log",
    "4": "text",
    # YAML/JSON use string type names
    "FLOAT": "float",
    "UNSIGNED": "uint",
    "CHAR": "string",
    "LOG": "log",
    "TEXT": "text",
}

_SNMP_TYPES = {0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18}
# Zabbix item types: 0=ZABBIX_ACTIVE, 2=TRAP, 3=SIMPLE, 4=INTERNAL, 5=ZABBIX_AGENT, 6=AGGREGATE, 7=HTTP_AGENT,
# 8=SNMP, 11=DB_MONITOR... We import ALL but flag non-SNMP ones
_SNMP_ITEM_TYPES = {"20", "SNMP_AGENT", "SNMPV1", "SNMPV2", "SNMPV3", "SNMP", "4"}

# Guess poll_class from Zabbix update interval
def _interval_to_class(interval: int) -> str:
    if interval <= 60:
        return "fast"
    if interval <= 600:
        return "slow"
    return "inventory"


def _parse_interval(raw: str | None) -> int:
    """Parse Zabbix interval string like '1m', '30s', '3600' → seconds int."""
    if not raw:
        return 60
    raw = str(raw).strip().lower()
    if raw.endswith("m"):
        return int(raw[:-1]) * 60
    if raw.endswith("h"):
        return int(raw[:-1]) * 3600
    if raw.endswith("d"):
        return int(raw[:-1]) * 86400
    if raw.endswith("s"):
        return int(raw[:-1])
    try:
        return int(raw)
    except (ValueError, TypeError):
        return 60


def _sanitize_key(raw: str) -> str:
    """Convert Zabbix item key to dot-notation NOCKO key."""
    key = raw.strip()
    # Remove Zabbix macro brackets and parameters: ifOperStatus[{#SNMPINDEX}] → ifOperStatus
    key = re.sub(r"\[.*?\]", "", key)
    key = re.sub(r"\{[^{}]+\}", "", key)
    # Replace invalid chars with dot
    key = re.sub(r"[^a-zA-Z0-9._-]", ".", key)
    key = re.sub(r"\.{2,}", ".", key).strip(".")
    return key or "item"


# ─── XML parser ───────────────────────────────────────────────────────────────
def _parse_xml(content: bytes) -> dict:
    root = ET.fromstring(content)
    warnings: list[str] = []

    # Support zabbix_export/templates and zabbix_version in root
    version = root.findtext("version", default="unknown")

    results = []
    templates_node = root.find("templates")
    if templates_node is None:
        warnings.append("No <templates> section found in XML.")
        return {"profile": {}, "templates": [], "warnings": warnings}

    all_templates = list(templates_node.findall("template"))
    if not all_templates:
        warnings.append("No <template> elements found.")
        return {"profile": {}, "templates": [], "warnings": warnings}

    # Use first template as the "profile"
    first = all_templates[0]
    profile_name = first.findtext("template", default=first.findtext("name", default="Imported Profile"))
    profile_desc = first.findtext("description", default="")

    for tmpl_node in all_templates:
        tmpl_name = tmpl_node.findtext("name", default=tmpl_node.findtext("template", default="Template"))
        tmpl_desc = tmpl_node.findtext("description", default="")

        items_node = tmpl_node.find("items")
        items: list[dict] = []
        if items_node is not None:
            for item in items_node.findall("item"):
                key_raw = item.findtext("key", default="")
                name = item.findtext("name", default=key_raw)
                type_id = item.findtext("type", default="0")
                value_type_raw = item.findtext("value_type", default="3")
                delay = item.findtext("delay", default="60")

                if not key_raw:
                    continue

                value_type = _ZBXTYPE_MAP.get(value_type_raw, "uint")
                interval = _parse_interval(delay)
                nocko_key = _sanitize_key(key_raw)

                if type_id not in _SNMP_ITEM_TYPES and type_id != "20":
                    warnings.append(f"Item '{key_raw}' is not SNMP type (type={type_id}), included anyway")

                items.append({
                    "key": nocko_key,
                    "name": name,
                    "value_type": value_type,
                    "poll_class": _interval_to_class(interval),
                    "interval_sec": interval,
                })

        if items:
            results.append({"name": tmpl_name, "description": tmpl_desc, "items": items})
        else:
            warnings.append(f"Template '{tmpl_name}' has no items — skipped.")

    profile = {
        "name": profile_name,
        "vendor": "Zabbix Import",
        "version": version,
        "description": profile_desc or f"Imported from Zabbix XML template (version {version})",
    }
    return {"profile": profile, "templates": results, "warnings": warnings}


# ─── JSON parser ──────────────────────────────────────────────────────────────
def _parse_json(content: bytes) -> dict:
    data = json.loads(content)
    warnings: list[str] = []

    # Zabbix JSON: { "zabbix_export": { "version": ..., "templates": [...] } }
    export = data.get("zabbix_export", data)
    version = str(export.get("version", "unknown"))
    zbx_templates = export.get("templates", [])

    if not zbx_templates:
        warnings.append("No 'templates' array found in JSON.")
        return {"profile": {}, "templates": [], "warnings": warnings}

    first = zbx_templates[0]
    profile_name = first.get("template", first.get("name", "Imported Profile"))
    profile_desc = first.get("description", "")

    results = []
    for tmpl in zbx_templates:
        tmpl_name = tmpl.get("name", tmpl.get("template", "Template"))
        tmpl_desc = tmpl.get("description", "")
        items: list[dict] = []

        for item in tmpl.get("items", []):
            key_raw = item.get("key", "")
            if not key_raw:
                continue
            name = item.get("name", key_raw)
            value_type_raw = str(item.get("value_type", "UNSIGNED")).upper()
            delay = str(item.get("delay", "60s"))
            item_type = str(item.get("type", "")).upper()

            value_type = _ZBXTYPE_MAP.get(value_type_raw, "uint")
            interval = _parse_interval(delay)
            nocko_key = _sanitize_key(key_raw)

            if item_type and item_type not in ("SNMP_AGENT", "SNMPV1", "SNMPV2", "SNMPV3", "SNMP", "4"):
                warnings.append(f"Item '{key_raw}' is type '{item_type}', included anyway")

            items.append({
                "key": nocko_key,
                "name": name,
                "value_type": value_type,
                "poll_class": _interval_to_class(interval),
                "interval_sec": interval,
            })

        if items:
            results.append({"name": tmpl_name, "description": tmpl_desc, "items": items})
        else:
            warnings.append(f"Template '{tmpl_name}' has no items — skipped.")

    profile = {
        "name": profile_name,
        "vendor": "Zabbix Import",
        "version": version,
        "description": profile_desc or f"Imported from Zabbix JSON template (version {version})",
    }
    return {"profile": profile, "templates": results, "warnings": warnings}


# ─── YAML parser ──────────────────────────────────────────────────────────────
def _parse_yaml(content: bytes) -> dict:
    try:
        import yaml  # type: ignore
    except ImportError:
        raise ValueError("PyYAML is not installed. Run: pip install pyyaml")

    data = yaml.safe_load(content)
    warnings: list[str] = []

    export = data.get("zabbix_export", data) if isinstance(data, dict) else {}
    version = str(export.get("version", "unknown"))
    zbx_templates = export.get("templates", [])

    if not zbx_templates:
        warnings.append("No 'templates' key found in YAML.")
        return {"profile": {}, "templates": [], "warnings": warnings}

    first = zbx_templates[0]
    profile_name = first.get("template", first.get("name", "Imported Profile"))
    profile_desc = first.get("description", "")

    results = []
    for tmpl in zbx_templates:
        tmpl_name = tmpl.get("name", tmpl.get("template", "Template"))
        tmpl_desc = tmpl.get("description", "")
        items: list[dict] = []

        for item in tmpl.get("items", []):
            key_raw = item.get("key", "")
            if not key_raw:
                continue
            name = item.get("name", key_raw)
            value_type_raw = str(item.get("value_type", "UNSIGNED")).upper()
            delay = str(item.get("delay", "60s"))
            item_type = str(item.get("type", "")).upper()

            value_type = _ZBXTYPE_MAP.get(value_type_raw, "uint")
            interval = _parse_interval(delay)
            nocko_key = _sanitize_key(key_raw)

            if item_type and item_type not in ("SNMP_AGENT", "SNMPV1", "SNMPV2", "SNMPV3", "SNMP"):
                warnings.append(f"Item '{key_raw}' is type '{item_type}', included anyway")

            items.append({
                "key": nocko_key,
                "name": name,
                "value_type": value_type,
                "poll_class": _interval_to_class(interval),
                "interval_sec": interval,
            })

        if items:
            results.append({"name": tmpl_name, "description": tmpl_desc, "items": items})
        else:
            warnings.append(f"Template '{tmpl_name}' has no items — skipped.")

    profile = {
        "name": profile_name,
        "vendor": "Zabbix Import",
        "version": version,
        "description": profile_desc or f"Imported from Zabbix YAML template (version {version})",
    }
    return {"profile": profile, "templates": results, "warnings": warnings}


# ─── Public entry point ───────────────────────────────────────────────────────
def parse_zabbix_template(content: bytes, filename: str) -> dict:
    """
    Auto-detect format from filename extension and parse.
    Returns: { profile, templates, warnings }
    Raises: ValueError on parse failure.
    """
    ext = Path(filename).suffix.lower()
    if ext in (".yaml", ".yml"):
        return _parse_yaml(content)
    if ext == ".json":
        return _parse_json(content)
    if ext == ".xml":
        return _parse_xml(content)

    # Fallback: try to sniff format
    stripped = content.lstrip()
    if stripped.startswith(b"<"):
        return _parse_xml(content)
    if stripped.startswith(b"{"):
        return _parse_json(content)
    # Try YAML last
    return _parse_yaml(content)
