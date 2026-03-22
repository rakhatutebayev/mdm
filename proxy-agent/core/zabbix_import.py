"""
Import Zabbix template exports (XML, JSON, YAML) into proxy-agent DeviceProfile.output_mapping.

Each mapping entry must include source_oid + target_key for snmp_poller.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ─── shared helpers (aligned with backend/zabbix_importer.py) ────────────────


def _sanitize_key(raw: str) -> str:
    key = raw.strip()
    key = re.sub(r"\[.*?\]", "", key)
    key = re.sub(r"\{[^{}]+\}", "", key)
    key = re.sub(r"[^a-zA-Z0-9._-]", ".", key)
    key = re.sub(r"\.{2,}", ".", key).strip(".")
    return key or "item"


def _parse_interval(raw: str | int | None) -> int:
    if raw is None:
        return 60
    if isinstance(raw, int):
        return max(1, raw)
    s = str(raw).strip().lower()
    if s.endswith("m"):
        return int(s[:-1] or "1") * 60
    if s.endswith("h"):
        return int(s[:-1] or "1") * 3600
    if s.endswith("d"):
        return int(s[:-1] or "1") * 86400
    if s.endswith("s"):
        return int(s[:-1] or "1")
    try:
        return int(s)
    except (ValueError, TypeError):
        return 60


def _interval_to_class(interval: int) -> str:
    if interval <= 60:
        return "fast"
    if interval <= 600:
        return "slow"
    return "inventory"


_VTYPE_MAP_STR = {
    "0": "float", "1": "string", "2": "log", "3": "uint", "4": "text",
    "FLOAT": "float", "UNSIGNED": "uint", "CHAR": "string", "LOG": "log", "TEXT": "text",
}


def _map_value_type(raw: Any) -> str:
    s = str(raw).strip().upper()
    if s in _VTYPE_MAP_STR:
        return _VTYPE_MAP_STR[s]
    return "uint"


def _slug_profile_id(name: str) -> str:
    return re.sub(r"[^a-z0-9_]", "_", name.lower().strip()) or "imported_profile"


def _mapping_row(
    *,
    snmp_oid: str,
    target_key: str,
    data_type: str,
    units: str = "",
    scale: float = 1.0,
    interval_sec: int = 60,
) -> dict[str, Any]:
    poll_class = _interval_to_class(interval_sec)
    return {
        "source_oid": snmp_oid.strip(),
        "target_key": target_key,
        "data_type": data_type,
        "unit": units or "",
        "scale_multiplier": scale,
        "poll_class": poll_class,
        "interval_sec": interval_sec,
    }


# ─── XML (Zabbix export) ─────────────────────────────────────────────────────


def _parse_xml(content: bytes) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    root = ET.fromstring(content)
    warnings: list[str] = []
    output_mapping: list[dict[str, Any]] = []

    tmpl = root.find(".//templates/template")
    profile_name = tmpl.findtext("name", "unknown") if tmpl is not None else "unknown"
    profile_id = _slug_profile_id(profile_name)

    for item in root.findall(".//items/item"):
        snmp_oid = (item.findtext("snmp_oid", "") or "").strip()
        key_raw = (item.findtext("key", "") or "").strip()
        if not snmp_oid or not key_raw:
            warnings.append(f"Skipped item (missing snmp_oid or key): {key_raw or snmp_oid}")
            continue

        units = item.findtext("units", "") or ""
        value_type_raw = item.findtext("value_type", "3")
        data_type = _map_value_type(value_type_raw)
        delay_raw = item.findtext("delay", "60")
        interval = _parse_interval(delay_raw)

        try:
            scale = float(item.findtext("multiplier", "1") or "1")
        except ValueError:
            scale = 1.0

        output_mapping.append(
            _mapping_row(
                snmp_oid=snmp_oid,
                target_key=_sanitize_key(key_raw),
                data_type=data_type,
                units=units,
                scale=scale,
                interval_sec=interval,
            )
        )

    return profile_id, profile_name, output_mapping, warnings


# ─── JSON / YAML (zabbix_export) ─────────────────────────────────────────────


def _items_from_template_dict(tmpl: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in tmpl.get("items") or []:
        if not isinstance(item, dict):
            continue
        oid = (
            str(item.get("snmp_oid", "") or item.get("SNMP_OID", "") or "").strip()
        )
        key_raw = str(item.get("key", "") or "").strip()
        if not oid or not key_raw:
            warnings.append(f"Skipped item without snmp_oid/key: {key_raw or oid!r}")
            continue

        name = str(item.get("name", "") or key_raw)
        units = str(item.get("units", "") or "")
        delay = item.get("delay", "60s")
        interval = _parse_interval(delay)
        data_type = _map_value_type(item.get("value_type", "UNSIGNED"))

        mult = item.get("multiplier") or item.get("custom_multiplier")
        try:
            scale = float(mult) if mult is not None else 1.0
        except (TypeError, ValueError):
            scale = 1.0

        rows.append(
            _mapping_row(
                snmp_oid=oid,
                target_key=_sanitize_key(key_raw),
                data_type=data_type,
                units=units,
                scale=scale,
                interval_sec=interval,
            )
        )
    return rows


def _parse_zabbix_dict(data: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    export = data.get("zabbix_export", data) if isinstance(data, dict) else {}
    if not isinstance(export, dict):
        return "imported_profile", "Imported", [], ["Invalid root: expected object"]

    templates = export.get("templates") or []
    if not templates or not isinstance(templates, list):
        return "imported_profile", "Imported", [], ["No templates[] in export"]

    first = templates[0]
    profile_name = str(
        first.get("name") or first.get("template") or "Imported Profile"
    )
    profile_id = _slug_profile_id(profile_name)

    output_mapping: list[dict[str, Any]] = []
    for tmpl in templates:
        if not isinstance(tmpl, dict):
            continue
        tmpl_name = str(tmpl.get("name") or tmpl.get("template") or "?")
        added = _items_from_template_dict(tmpl, warnings)
        if not added:
            warnings.append(f"Template {tmpl_name!r}: no SNMP items with snmp_oid")
        output_mapping.extend(added)

    return profile_id, profile_name, output_mapping, warnings


def _parse_json(content: bytes) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    text = content.decode("utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        return "imported_profile", "Imported", [], ["JSON root must be an object"]
    return _parse_zabbix_dict(data)


def _parse_yaml(content: bytes) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise ValueError("PyYAML не установлен. pip install pyyaml") from e

    data = yaml.safe_load(content.decode("utf-8-sig"))
    if not isinstance(data, dict):
        return "imported_profile", "Imported", [], ["YAML root must be a mapping"]
    return _parse_zabbix_dict(data)


# ─── public API ───────────────────────────────────────────────────────────────


def parse_zabbix_template_bytes(content: bytes, filename: str) -> tuple[str, str, list[dict[str, Any]], list[str]]:
    """
    Auto-detect format, return (profile_id, profile_name, output_mapping, warnings).
    """
    ext = Path(filename or "").suffix.lower()
    stripped = content.lstrip()

    if ext in (".yaml", ".yml"):
        return _parse_yaml(content)
    if ext == ".json":
        return _parse_json(content)
    if ext == ".xml" or stripped.startswith(b"<"):
        return _parse_xml(content)
    if stripped.startswith(b"{"):
        return _parse_json(content)

    # try YAML as last resort (Zabbix may use .txt)
    try:
        return _parse_yaml(content)
    except Exception:
        pass

    raise ValueError(
        f"Не удалось определить формат файла {filename!r}. "
        "Используйте .xml, .json, .yaml или .yml (экспорт шаблона Zabbix)."
    )
