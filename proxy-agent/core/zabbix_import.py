"""
Import Zabbix template exports (XML, JSON, YAML) into proxy-agent DeviceProfile.output_mapping.

Supports 3 item types:
  - "get"       : SNMP_AGENT with scalar/get[OID] → direct SNMP GET per poll cycle
  - "walk"      : SNMP_AGENT with walk[OID1, OID2, ...] → SNMP BULKWALK, stored in walk_cache
  - "dependent" : DEPENDENT items → extract value from walk_cache via SNMP_WALK_VALUE preprocessing
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

# ─── shared helpers ───────────────────────────────────────────────────────────


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


# ─── NEW: OID format helpers ──────────────────────────────────────────────────


def _parse_walk_oids(snmp_oid_raw: str) -> list[str]:
    """Parse 'walk[OID1, OID2, ...]' → list of bare OID strings."""
    m = re.match(r"^\s*walk\[(.+)\]\s*$", snmp_oid_raw, re.IGNORECASE)
    if not m:
        return []
    return [p.strip() for p in m.group(1).split(",") if p.strip()]


def _unwrap_get_oid(snmp_oid_raw: str) -> str:
    """'get[1.3.6.1.2.1.1.1.0]' → '1.3.6.1.2.1.1.1.0'; bare OID → unchanged."""
    m = re.match(r"^\s*get\[(.+)\]\s*$", snmp_oid_raw, re.IGNORECASE)
    return m.group(1).strip() if m else snmp_oid_raw.strip()


def _extract_snmp_walk_value_preprocessing(item: dict) -> tuple[str, str]:
    """
    Find SNMP_WALK_VALUE preprocessing step and extract (base_oid, index_mode).
    base_oid: OID prefix without trailing .{#SNMPINDEX}
    index_mode: "0" or "1" (from parameters[1])
    Returns ("", "0") if not found.
    """
    for step in item.get("preprocessing") or []:
        if not isinstance(step, dict):
            continue
        if str(step.get("type", "")).upper() == "SNMP_WALK_VALUE":
            params = step.get("parameters") or []
            if params and isinstance(params, list):
                oid_template = str(params[0]).strip()
                # Strip trailing .{#ANYMACRO} to get the base OID
                base = re.sub(r"\.\{#[^}]+\}$", "", oid_template).strip()
                mode = str(params[1]).strip() if len(params) > 1 else "0"
                return base, mode
    return "", "0"


def _extract_lld_macros(discovery_rule: dict) -> dict[str, str]:
    """
    Extract {#MACRO} → base_OID mapping from SNMP_WALK_TO_JSON preprocessing.
    Used to resolve LLD macro values (e.g. {#FAN_DESCR}) from walk results.
    Format in Zabbix: parameters = [macro1, oid1, mode1, macro2, oid2, mode2, ...]
    """
    macros: dict[str, str] = {}
    for step in (discovery_rule.get("preprocessing") or []):
        if not isinstance(step, dict):
            continue
        if str(step.get("type", "")).upper() == "SNMP_WALK_TO_JSON":
            params = step.get("parameters") or []
            if isinstance(params, list):
                i = 0
                while i + 1 < len(params):
                    macro = str(params[i]).strip()
                    oid = str(params[i + 1]).strip() if i + 1 < len(params) else ""
                    if macro.startswith("{#") and oid:
                        macros[macro] = oid
                    i += 3  # macro, oid, mode — step over 3 items
    return macros


# ─── mapping row builders ─────────────────────────────────────────────────────


def _mapping_row(
    *,
    snmp_oid: str,
    target_key: str,
    data_type: str,
    units: str = "",
    scale: float = 1.0,
    interval_sec: int = 60,
) -> dict[str, Any]:
    """Build a scalar GET row (backward-compatible base format)."""
    poll_class = _interval_to_class(interval_sec)
    return {
        "snmp_type": "get",
        "source_oid": snmp_oid.strip(),
        "target_key": target_key,
        "data_type": data_type,
        "unit": units or "",
        "scale_multiplier": scale,
        "poll_class": poll_class,
        "interval_sec": interval_sec,
    }


def _walk_row(
    *,
    walk_oids: list[str],
    target_key: str,
    data_type: str,
    units: str = "",
    interval_sec: int = 60,
) -> dict[str, Any]:
    """Build a SNMP WALK master-item row."""
    poll_class = _interval_to_class(interval_sec)
    return {
        "snmp_type": "walk",
        "source_oid": walk_oids[0] if walk_oids else "",
        "walk_oids": walk_oids,
        "target_key": target_key,
        "data_type": data_type,
        "unit": units or "",
        "scale_multiplier": 1.0,
        "poll_class": poll_class,
        "interval_sec": interval_sec,
    }


def _dependent_row(
    *,
    master_key: str,
    walk_extract_oid: str,
    walk_extract_mode: str,
    target_key_sanitized: str,
    target_key_raw: str,
    lld_macros: dict[str, str],
    data_type: str,
    units: str = "",
    scale: float = 1.0,
    interval_sec: int = 60,
) -> dict[str, Any]:
    """Build a DEPENDENT item row (extracted from walk_cache)."""
    poll_class = _interval_to_class(interval_sec)
    return {
        "snmp_type": "dependent",
        "source_oid": "",
        "master_key": master_key,
        "walk_extract_oid": walk_extract_oid,
        "walk_extract_mode": walk_extract_mode,
        "target_key": target_key_sanitized,
        "target_key_raw": target_key_raw,
        "lld_macros": lld_macros,
        "data_type": data_type,
        "unit": units or "",
        "scale_multiplier": scale,
        "poll_class": poll_class,
        "interval_sec": interval_sec,
    }


# ─── import meta ──────────────────────────────────────────────────────────────


def _build_import_meta(
    *,
    template_description: str,
    output_mapping: list[dict[str, Any]],
    discovery_rules_count: int,
    zabbix_export_version: str,
) -> dict[str, Any]:
    """
    Structured notes shown in Local Console after import.
    """
    walk_count = sum(1 for r in output_mapping if r.get("snmp_type") == "walk")
    dep_count = sum(1 for r in output_mapping if r.get("snmp_type") == "dependent")
    lld_legacy = sum(
        1 for r in output_mapping
        if r.get("snmp_type") not in ("walk", "dependent")
        and "{#" in str(r.get("source_oid", "") or "")
    )
    scalar = len(output_mapping) - walk_count - dep_count - lld_legacy
    desc = (template_description or "").strip()
    if len(desc) > 50_000:
        desc = desc[:50_000] + "\n… [обрезано]"

    playbook: list[str] = [
        "Zabbix → NOCKO profile import. Below is how the agent will process this template.",
        f"Zabbix export version: {zabbix_export_version or '—'}; discovery rules: {discovery_rules_count}.",
        (
            f"output_mapping rows: {len(output_mapping)} — "
            f"scalar GET: {scalar}; walk masters: {walk_count}; "
            f"dependent (extracted from walk): {dep_count}; legacy LLD macros: {lld_legacy}."
        ),
        "Poll classes: interval ≤60s → fast; ≤600s → slow; else → inventory.",
    ]
    if scalar + walk_count > 0:
        playbook.append(
            "Action: add a device on /devices (UID, IP, this profile_id, SNMP credentials). "
            "Check Verify SNMP and /diagnostics."
        )
    else:
        playbook.append(
            "No scalar or walk items found — SNMP collection will not run until items with OIDs are present."
        )
    if walk_count > 0:
        playbook.append(
            f"{walk_count} SNMP BULKWALK master item(s) found. Agent will execute walk[] per poll cycle "
            f"and cache results for {dep_count} dependent item(s)."
        )
    if dep_count > 0 and "lld" in str(output_mapping).lower():
        playbook.append(
            "LLD prototypes (fans, disks, etc.) will enumerate instances dynamically from walk results. "
            "Each discovered instance gets its own metric key."
        )
    if lld_legacy > 0:
        playbook.append(
            f"{lld_legacy} legacy LLD OIDs with {{#...}} macros cannot be polled directly (no walk master found). "
            "These will be skipped by the poller."
        )

    return {
        "zabbix_export_version": zabbix_export_version,
        "template_description": desc,
        "discovery_rules_count": discovery_rules_count,
        "stats": {
            "scalar_mapping_rows": scalar,
            "walk_master_rows": walk_count,
            "dependent_rows": dep_count,
            "lld_prototype_rows": lld_legacy,
            "total_mapping_rows": len(output_mapping),
        },
        "agent_playbook": playbook,
    }


# ─── item parser ──────────────────────────────────────────────────────────────

# Item types that Zabbix marks as DEPENDENT
_DEPENDENT_TYPES = {"DEPENDENT"}
# Item types that cannot be polled by the agent at all
_SKIP_TYPES = {"CALCULATED", "INTERNAL", "SNMP_TRAP", "TRAPPER", "SIMPLE", "EXTERNAL",
               "DB_MONITOR", "IPMI", "SSH", "TELNET", "ZABBIX_ACTIVE", "ZABBIX_PASSIVE",
               "HTTP_AGENT", "SCRIPT", "BROWSER"}

# Item types that hint at a specific non-SNMP technology
_VMWARE_KEY_PREFIXES = ("vmware.", "icmpping")
_HTTP_TYPES = {"HTTP_AGENT", "SCRIPT", "BROWSER"}
_IPMI_TYPES = {"IPMI"}
_SIMPLE_TYPES = {"SIMPLE"}


def _detect_template_technology(templates: list[dict[str, Any]]) -> str:
    """
    Scan all items in all templates to identify the monitoring technology.
    Returns a short human-readable tag: "vmware", "http_agent", "ipmi", "simple",
    "mixed_non_snmp", or "unknown_non_snmp".
    """
    type_counts: dict[str, int] = {}
    vmware_keys = 0
    for tmpl in templates:
        for item in (tmpl.get("items") or []):
            t = str(item.get("type", "")).upper()
            type_counts[t] = type_counts.get(t, 0) + 1
            key = str(item.get("key", "")).lower()
            if any(key.startswith(p) for p in _VMWARE_KEY_PREFIXES):
                vmware_keys += 1
        for dr in (tmpl.get("discovery_rules") or []):
            t = str(dr.get("type", "")).upper()
            type_counts[t] = type_counts.get(t, 0) + 1
            key = str(dr.get("key", "")).lower()
            if any(key.startswith(p) for p in _VMWARE_KEY_PREFIXES):
                vmware_keys += 1

    if vmware_keys > 0:
        return "vmware"
    if type_counts.get("IPMI", 0) > 0 and not type_counts.get("SNMP_AGENT", 0):
        return "ipmi"
    http_cnt = sum(type_counts.get(t, 0) for t in _HTTP_TYPES)
    simple_cnt = type_counts.get("SIMPLE", 0)
    snmp_cnt = type_counts.get("SNMP_AGENT", 0)
    if http_cnt > 0 and snmp_cnt == 0:
        return "http_agent"
    if simple_cnt > 0 and snmp_cnt == 0 and http_cnt == 0:
        return "simple"
    if snmp_cnt == 0 and type_counts:
        return "mixed_non_snmp"
    return "unknown_non_snmp"



def _row_from_item_dict(
    item: dict[str, Any],
    warnings: list[str],
    ctx: str,
    *,
    master_key: str = "",
    lld_macros: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    """
    Parse a Zabbix item or item_prototype dict into an output_mapping row.

    snmp_type logic:
      - SNMP_AGENT + walk[...] OID      → "walk"
      - SNMP_AGENT + get[OID] / bare    → "get"
      - DEPENDENT (any oid)             → "dependent" (needs master_key)
      - Other types (CALCULATED, etc.)  → None (skip)
    """
    item_type = str(item.get("type", "SNMP_AGENT")).upper().replace(" ", "_")
    key_raw = str(item.get("key", "") or "").strip()
    oid = str(item.get("snmp_oid", "") or item.get("SNMP_OID", "") or "").strip()
    units = str(item.get("units", "") or "")
    delay = item.get("delay", "60s")
    interval = _parse_interval(delay)
    data_type = _map_value_type(item.get("value_type", "UNSIGNED"))
    mult = item.get("multiplier") or item.get("custom_multiplier")
    try:
        scale = float(mult) if mult is not None else 1.0
    except (TypeError, ValueError):
        scale = 1.0

    # ── DEPENDENT items ──────────────────────────────────────────────────────
    if item_type in _DEPENDENT_TYPES or (not oid and master_key):
        walk_oid, walk_mode = _extract_snmp_walk_value_preprocessing(item)
        if not walk_oid:
            warnings.append(
                f"{ctx}: DEPENDENT item {key_raw!r} has no SNMP_WALK_VALUE preprocessing, skipping"
            )
            return None
        if not master_key:
            warnings.append(
                f"{ctx}: DEPENDENT item {key_raw!r} missing master_key context, skipping"
            )
            return None
        return _dependent_row(
            master_key=master_key,
            walk_extract_oid=walk_oid,
            walk_extract_mode=walk_mode,
            target_key_sanitized=_sanitize_key(key_raw),
            target_key_raw=key_raw,
            lld_macros=lld_macros or {},
            data_type=data_type,
            units=units,
            scale=scale,
            interval_sec=interval,
        )

    # ── VMware SIMPLE items ──────────────────────────────────────────────────
    # Intercept before generic _SKIP_TYPES drop — vmware.* keys from SIMPLE items
    # get their own collector_type so vmware_poller can pick them up.
    if item_type == "SIMPLE" and key_raw:
        key_lower = key_raw.lower()
        if key_lower.startswith("vmware.") or key_lower.startswith("icmpping"):
            # Determine poll class from key pattern
            if any(k in key_lower for k in ("perf", "usage", "powerstate", "state", "status")):
                poll_class = "fast"
            elif any(k in key_lower for k in ("size", "free", "datastore", "storage", "committed")):
                poll_class = "slow"
            else:
                poll_class = "slow"  # conservative default
            return {
                "key": _sanitize_key(key_raw),
                "vmware_key": key_raw,
                "collector_type": "vmware",
                "poll_class": poll_class,
                "unit": units,
                "data_type": data_type,
                "scale": scale,
                "interval_sec": interval,
            }

    # ── Skip non-SNMP types ──────────────────────────────────────────────────
    if item_type in _SKIP_TYPES:
        return None  # silently skip


    # ── SNMP_AGENT: needs an OID ─────────────────────────────────────────────
    if not oid:
        warnings.append(f"{ctx}: skipped {key_raw!r} — no snmp_oid and not DEPENDENT")
        return None

    # ── Walk master ──────────────────────────────────────────────────────────
    if oid.lower().startswith("walk["):
        walk_oids = _parse_walk_oids(oid)
        if not walk_oids:
            warnings.append(f"{ctx}: could not parse walk OIDs from {oid!r}, skipping")
            return None
        if not key_raw:
            warnings.append(f"{ctx}: walk item missing key, skipping")
            return None
        return _walk_row(
            walk_oids=walk_oids,
            target_key=_sanitize_key(key_raw),
            data_type=data_type,
            units=units,
            interval_sec=interval,
        )

    # ── Scalar GET ───────────────────────────────────────────────────────────
    bare_oid = _unwrap_get_oid(oid)
    if not bare_oid or not key_raw:
        warnings.append(f"{ctx}: skipped item without snmp_oid/key ({key_raw or oid!r})")
        return None
    return _mapping_row(
        snmp_oid=bare_oid,
        target_key=_sanitize_key(key_raw),
        data_type=data_type,
        units=units,
        scale=scale,
        interval_sec=interval,
    )


def _items_from_template_dict(tmpl: dict[str, Any], warnings: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    tmpl_name = str(tmpl.get("name") or tmpl.get("template") or "?")

    # ── Regular items ────────────────────────────────────────────────────────
    for item in tmpl.get("items") or []:
        if not isinstance(item, dict):
            continue
        row = _row_from_item_dict(item, warnings, f"Template {tmpl_name!r}")
        if row:
            rows.append(row)

    # ── Discovery rules + item_prototypes ────────────────────────────────────
    for dr in tmpl.get("discovery_rules") or []:
        if not isinstance(dr, dict):
            continue
        dr_name = str(dr.get("name") or "?")
        dr_type = str(dr.get("type", "SNMP_AGENT")).upper().replace(" ", "_")
        dr_oid_raw = str(dr.get("snmp_oid", "") or "").strip()
        dr_key = str(dr.get("key", "") or "").strip()
        dr_delay = dr.get("delay", "3600s")

        # ── Parse Zabbix LLD discovery[] OID format ──────────────────────────
        # Format: discovery[{#SNMPVALUE},1.3.6.1.4.1.6876.2.1.1.2]
        lld_base_oid = ""
        if dr_oid_raw.lower().startswith("discovery["):
            m = re.search(r"discovery\[.*?,\s*([0-9][0-9.]+)\s*\]", dr_oid_raw, re.IGNORECASE)
            if m:
                lld_base_oid = m.group(1).strip(".")

        # Create a walk master row for the discovery rule OID
        if lld_base_oid and dr_type == "SNMP_AGENT":
            master_row = _walk_row(
                walk_oids=[lld_base_oid],
                target_key=_sanitize_key(dr_key),
                data_type="text",
                units="",
                interval_sec=_parse_interval(dr_delay),
            )
            rows.append(master_row)

        # Extract {#MACRO} → OID mapping from SNMP_WALK_TO_JSON preprocessing
        dr_lld_macros = _extract_lld_macros(dr)

        # Resolve master item key for DEPENDENT prototypes
        proto_master_key = ""
        if isinstance(dr.get("master_item"), dict):
            proto_master_key = str(dr["master_item"].get("key", ""))

        for proto in dr.get("item_prototypes") or []:
            if not isinstance(proto, dict):
                continue
            proto_type = str(proto.get("type", "SNMP_AGENT")).upper().replace(" ", "_")
            proto_oid = str(proto.get("snmp_oid", "") or "").strip()
            proto_key_raw = str(proto.get("key", "") or "").strip()

            # ── LLD-indexed: SNMP items with OID.{#SNMPINDEX} ─────────────────
            # Walk the parent discovery OID to enumerate indices, then:
            # GET column_oid.INDEX for each discovered index.
            if (
                proto_type == "SNMP_AGENT"
                and proto_oid
                and "{#SNMPINDEX}" in proto_oid.upper()
                and lld_base_oid
            ):
                col_oid = re.sub(r"[.\s]*\{#SNMPINDEX\}.*$", "", proto_oid, flags=re.IGNORECASE).strip(".")
                units = str(proto.get("units", "") or "")
                delay = proto.get("delay", "60s")
                interval = _parse_interval(delay)
                data_type = _map_value_type(proto.get("value_type", "UNSIGNED"))
                mult = proto.get("multiplier") or proto.get("custom_multiplier")
                try:
                    scale = float(mult) if mult is not None else 1.0
                except (TypeError, ValueError):
                    scale = 1.0

                rows.append({
                    "snmp_type": "lld_indexed",
                    "key": _sanitize_key(proto_key_raw),
                    "key_raw": proto_key_raw,
                    "snmp_oid": col_oid,
                    "lld_walk_oid": lld_base_oid,
                    "lld_master_key": _sanitize_key(dr_key),
                    "data_type": data_type,
                    "unit": units,
                    "scale": scale,
                    "interval_sec": interval,
                    "poll_class": "fast" if interval <= 120 else "slow",
                })
                continue

            # ── DEPENDENT item_prototypes (standard walk+preprocessing) ───────
            item_master = proto_master_key
            if isinstance(proto.get("master_item"), dict):
                item_master = str(proto["master_item"].get("key", "")) or item_master

            row = _row_from_item_dict(
                proto,
                warnings,
                f"Discovery {dr_name!r}",
                master_key=item_master,
                lld_macros=dr_lld_macros,
            )
            if row:
                rows.append(row)

    return rows



def _normalize_templates_list(raw: Any) -> list[dict[str, Any]]:
    """
    Zabbix YAML sometimes has `templates:` as one mapping (single template)
    instead of a list — PyYAML loads that as dict, not [dict].
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return [t for t in raw if isinstance(t, dict)]
    if isinstance(raw, dict):
        if any(k in raw for k in ("items", "discovery_rules", "name", "template", "uuid", "groups")):
            return [raw]
        if raw and all(isinstance(v, dict) for v in raw.values()):
            return [v for v in raw.values() if isinstance(v, dict)]
        return [raw]
    return []


# ─── XML (Zabbix export) ─────────────────────────────────────────────────────


def _parse_xml(content: bytes) -> tuple[str, str, list[dict[str, Any]], list[str], dict[str, Any]]:
    root = ET.fromstring(content)
    warnings: list[str] = []
    output_mapping: list[dict[str, Any]] = []

    tmpl = root.find(".//templates/template")
    profile_name = tmpl.findtext("name", "unknown") if tmpl is not None else "unknown"
    profile_id = _slug_profile_id(profile_name)
    tmpl_desc = (
        (tmpl.findtext("description", "") or "").strip()
        if tmpl is not None
        else ""
    )
    discovery_n = len(root.findall(".//discovery_rule"))

    for item in root.findall(".//items/item"):
        snmp_oid = (item.findtext("snmp_oid", "") or "").strip()
        key_raw = (item.findtext("key", "") or "").strip()
        if not key_raw:
            warnings.append(f"Skipped XML item with no key: {snmp_oid[:50]!r}")
            continue
        if not snmp_oid:
            warnings.append(f"Skipped XML item {key_raw!r} — no snmp_oid")
            continue

        item_type = (item.findtext("type", "SNMP_AGENT") or "SNMP_AGENT").upper()
        units = item.findtext("units", "") or ""
        value_type_raw = item.findtext("value_type", "3")
        data_type = _map_value_type(value_type_raw)
        delay_raw = item.findtext("delay", "60")
        interval = _parse_interval(delay_raw)
        try:
            scale = float(item.findtext("multiplier", "1") or "1")
        except ValueError:
            scale = 1.0

        # Reuse the unified parser
        fake_item = {
            "type": item_type,
            "key": key_raw,
            "snmp_oid": snmp_oid,
            "units": units,
            "value_type": value_type_raw,
            "delay": delay_raw,
            "multiplier": str(scale),
        }
        row = _row_from_item_dict(fake_item, warnings, f"XML template {profile_name!r}")
        if row:
            output_mapping.append(row)

    import_meta = _build_import_meta(
        template_description=tmpl_desc,
        output_mapping=output_mapping,
        discovery_rules_count=discovery_n,
        zabbix_export_version="",
    )
    return profile_id, profile_name, output_mapping, warnings, import_meta


# ─── JSON / YAML (zabbix_export) ─────────────────────────────────────────────


def _parse_zabbix_dict(data: dict[str, Any]) -> tuple[str, str, list[dict[str, Any]], list[str], dict[str, Any]]:
    warnings: list[str] = []
    export = data.get("zabbix_export", data) if isinstance(data, dict) else {}
    if not isinstance(export, dict):
        return "imported_profile", "Imported", [], ["Invalid root: expected object"], {}

    templates = _normalize_templates_list(export.get("templates"))
    if not templates:
        warnings.append(
            "No templates found under zabbix_export.templates (expected a list or one template object)."
        )
        return "imported_profile", "Imported", [], warnings, {}

    first = templates[0]
    profile_name = str(first.get("name") or first.get("template") or "Imported Profile")
    profile_id = _slug_profile_id(profile_name)

    zabbix_ver = str(export.get("version") or "").strip()
    template_description = ""
    discovery_total = 0

    output_mapping: list[dict[str, Any]] = []
    for tmpl in templates:
        if not isinstance(tmpl, dict):
            continue
        tmpl_name = str(tmpl.get("name") or tmpl.get("template") or "?")
        discovery_total += len(tmpl.get("discovery_rules") or [])
        if not template_description.strip():
            raw_desc = tmpl.get("description")
            if isinstance(raw_desc, str) and raw_desc.strip():
                template_description = raw_desc.strip()
        added = _items_from_template_dict(tmpl, warnings)
        if not added:
            warnings.append(
                f"Template {tmpl_name!r}: no SNMP items found (check items[] and discovery_rules.item_prototypes[] for snmp_oid + key)"
            )
        output_mapping.extend(added)

    import_meta = _build_import_meta(
        template_description=template_description,
        output_mapping=output_mapping,
        discovery_rules_count=discovery_total,
        zabbix_export_version=zabbix_ver,
    )
    # Detect non-SNMP technology for better error messages on import
    if not output_mapping:
        import_meta["template_technology"] = _detect_template_technology(templates)
    return profile_id, profile_name, output_mapping, warnings, import_meta


def _parse_json(content: bytes) -> tuple[str, str, list[dict[str, Any]], list[str], dict[str, Any]]:
    text = content.decode("utf-8-sig")
    data = json.loads(text)
    if not isinstance(data, dict):
        return "imported_profile", "Imported", [], ["JSON root must be an object"], {}
    return _parse_zabbix_dict(data)


def _parse_yaml(content: bytes) -> tuple[str, str, list[dict[str, Any]], list[str], dict[str, Any]]:
    try:
        import yaml  # type: ignore
    except ImportError as e:
        raise ValueError("PyYAML not installed. pip install pyyaml") from e

    data = yaml.safe_load(content.decode("utf-8-sig"))
    if not isinstance(data, dict):
        return "imported_profile", "Imported", [], ["YAML root must be a mapping"], {}
    return _parse_zabbix_dict(data)


# ─── public API ───────────────────────────────────────────────────────────────


def parse_zabbix_template_bytes(
    content: bytes, filename: str
) -> tuple[str, str, list[dict[str, Any]], list[str], dict[str, Any]]:
    """
    Auto-detect format (XML / JSON / YAML).

    Returns (profile_id, profile_name, output_mapping, warnings, import_meta).
    import_meta keys: template_description, agent_playbook, stats, zabbix_export_version.
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

    # Last resort: try YAML
    try:
        return _parse_yaml(content)
    except Exception:
        pass

    raise ValueError(
        f"Cannot detect format for {filename!r}. "
        "Use .xml, .json, .yaml or .yml (Zabbix template export)."
    )
