#!/usr/bin/env python3
"""SNMP utility for discovering Avaya phones (including 1608) in a subnet.

Standalone helper script intentionally kept outside backend/frontend runtime.

Examples:
  python3 utils/avaya_1608_snmp_probe.py --subnet 192.168.1.0/24 --community public
  python3 utils/avaya_1608_snmp_probe.py --hosts 192.168.1.10,192.168.1.11 --json-out phones.json --csv-out phones.csv
"""

from __future__ import annotations

import argparse
import csv
import ipaddress
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        getCmd,
        nextCmd,
    )
except Exception as exc:  # pragma: no cover - runtime dependency guard
    print(
        "Missing dependency: pysnmp\n"
        "Install with: python3 -m pip install pysnmp\n"
        f"Import error: {exc}",
        file=sys.stderr,
    )
    raise SystemExit(2)


BASE_OIDS = {
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "sys_uptime": "1.3.6.1.2.1.1.3.0",
}

# ENTITY-MIB subtree OIDs (often present on desk phones)
ENTITY_MODEL_SUBTREE = "1.3.6.1.2.1.47.1.1.1.1.13"
ENTITY_SERIAL_SUBTREE = "1.3.6.1.2.1.47.1.1.1.1.11"
ENTITY_FW_SUBTREE = "1.3.6.1.2.1.47.1.1.1.1.10"

# IF-MIB first interface MAC as fallback
IF_PHYS_ADDRESS_1 = "1.3.6.1.2.1.2.2.1.6.1"


@dataclass
class ProbeConfig:
    community: str
    port: int
    timeout_s: float
    retries: int


def _safe_str(value: Any) -> str:
    text = str(value or "").strip()
    if text.startswith("0x"):
        # Pretty-print hex bytes if pysnmp returns opaque octets as hex literal.
        try:
            raw = bytes.fromhex(text[2:])
            return ":".join(f"{b:02X}" for b in raw)
        except Exception:
            return text
    return text


def _snmp_get(ip: str, oid: str, cfg: ProbeConfig) -> str:
    iterator = getCmd(
        SnmpEngine(),
        CommunityData(cfg.community, mpModel=1),  # SNMPv2c
        UdpTransportTarget((ip, cfg.port), timeout=cfg.timeout_s, retries=cfg.retries),
        ContextData(),
        ObjectType(ObjectIdentity(oid)),
    )
    error_indication, error_status, _error_index, var_binds = next(iterator)
    if error_indication or error_status:
        return ""
    for _name, value in var_binds:
        return _safe_str(value)
    return ""


def _snmp_first_subtree_value(ip: str, subtree_oid: str, cfg: ProbeConfig, max_rows: int = 20) -> str:
    count = 0
    for (
        error_indication,
        error_status,
        _error_index,
        var_binds,
    ) in nextCmd(
        SnmpEngine(),
        CommunityData(cfg.community, mpModel=1),
        UdpTransportTarget((ip, cfg.port), timeout=cfg.timeout_s, retries=cfg.retries),
        ContextData(),
        ObjectType(ObjectIdentity(subtree_oid)),
        lexicographicMode=False,
    ):
        if error_indication or error_status:
            return ""
        for _name, value in var_binds:
            text = _safe_str(value)
            if text:
                return text
        count += 1
        if count >= max_rows:
            break
    return ""


def probe_host(ip: str, cfg: ProbeConfig) -> dict[str, Any]:
    sys_descr = _snmp_get(ip, BASE_OIDS["sys_descr"], cfg)
    if not sys_descr:
        return {
            "ip": ip,
            "reachable": False,
            "vendor": "",
            "model": "",
            "serial": "",
            "mac": "",
            "firmware": "",
            "sys_name": "",
            "sys_descr": "",
            "uptime": "",
        }

    sys_name = _snmp_get(ip, BASE_OIDS["sys_name"], cfg)
    uptime = _snmp_get(ip, BASE_OIDS["sys_uptime"], cfg)
    model = _snmp_first_subtree_value(ip, ENTITY_MODEL_SUBTREE, cfg)
    serial = _snmp_first_subtree_value(ip, ENTITY_SERIAL_SUBTREE, cfg)
    firmware = _snmp_first_subtree_value(ip, ENTITY_FW_SUBTREE, cfg)
    mac = _snmp_get(ip, IF_PHYS_ADDRESS_1, cfg)

    combined = " ".join([sys_descr, sys_name, model]).lower()
    vendor = "Avaya" if "avaya" in combined else ""

    # Best-effort model inference if entity model subtree is empty.
    if not model and "1608" in combined:
        model = "Avaya 1608"

    return {
        "ip": ip,
        "reachable": True,
        "vendor": vendor,
        "model": model,
        "serial": serial,
        "mac": mac,
        "firmware": firmware,
        "sys_name": sys_name,
        "sys_descr": sys_descr,
        "uptime": uptime,
    }


def expand_targets(subnet: str | None, hosts: str | None) -> list[str]:
    targets: list[str] = []
    if subnet:
        network = ipaddress.ip_network(subnet, strict=False)
        targets.extend(str(host) for host in network.hosts())
    if hosts:
        for item in hosts.split(","):
            token = item.strip()
            if token:
                ipaddress.ip_address(token)  # validate
                targets.append(token)
    unique = sorted(set(targets), key=lambda v: tuple(int(x) for x in v.split(".")))
    return unique


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "ip",
        "reachable",
        "vendor",
        "model",
        "serial",
        "mac",
        "firmware",
        "sys_name",
        "sys_descr",
        "uptime",
    ]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Discover Avaya phones (e.g., 1608) via SNMP in a subnet.",
    )
    parser.add_argument("--subnet", help="CIDR subnet to scan, e.g. 192.168.1.0/24")
    parser.add_argument("--hosts", help="Comma-separated host IPs")
    parser.add_argument("--community", default="public", help="SNMP v2c community string")
    parser.add_argument("--port", type=int, default=161, help="SNMP UDP port")
    parser.add_argument("--timeout", type=float, default=0.8, help="SNMP timeout per request (seconds)")
    parser.add_argument("--retries", type=int, default=0, help="SNMP retries")
    parser.add_argument("--workers", type=int, default=32, help="Parallel workers")
    parser.add_argument("--only-avaya", action="store_true", help="Show only hosts identified as Avaya")
    parser.add_argument("--json-out", help="Write JSON output to file")
    parser.add_argument("--csv-out", help="Write CSV output to file")
    args = parser.parse_args()

    if not args.subnet and not args.hosts:
        parser.error("Provide at least one target source: --subnet or --hosts")

    try:
        targets = expand_targets(args.subnet, args.hosts)
    except ValueError as exc:
        print(f"Invalid target input: {exc}", file=sys.stderr)
        return 2

    if not targets:
        print("No targets to scan.", file=sys.stderr)
        return 1

    cfg = ProbeConfig(
        community=args.community,
        port=args.port,
        timeout_s=args.timeout,
        retries=args.retries,
    )

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {executor.submit(probe_host, ip, cfg): ip for ip in targets}
        for future in as_completed(futures):
            rows.append(future.result())

    rows.sort(key=lambda item: tuple(int(x) for x in item["ip"].split(".")))
    if args.only_avaya:
        rows = [row for row in rows if row["vendor"] == "Avaya"]

    output = {
        "scanned_hosts": len(targets),
        "matched_hosts": len(rows),
        "results": rows,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))

    if args.json_out:
        path = Path(args.json_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.csv_out:
        path = Path(args.csv_out)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_csv(path, rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
