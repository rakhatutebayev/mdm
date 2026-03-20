#!/usr/bin/env python3
"""
Сбор состояния хранилища с Dell iDRAC по SNMP v2c (Dell Storage / PERC MIB).

Ветки OID ориентированы на iDRAC 8/9 и новые PERC. На iDRAC6 таблицы часто пустые
или неполные — тогда смотрите PERCCLI на ESXi или Redfish на новых BMC.

Зависимости: pip install 'pysnmp<5'  (совместимо с pyasn1<0.5 как в proxy_agent)

Пример:
  python3 scripts/dell_idrac_storage_snmp.py --host 192.168.1.120 --community public --format json
  python3 scripts/dell_idrac_storage_snmp.py --host 192.168.1.120 --community public --format table
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Any

try:
    from pysnmp.hlapi import (
        CommunityData,
        ContextData,
        ObjectIdentity,
        ObjectType,
        SnmpEngine,
        UdpTransportTarget,
        nextCmd,
    )
except ImportError as exc:
    print("Установите pysnmp: pip install 'pysnmp<5'", file=sys.stderr)
    raise SystemExit(2) from exc


# Dell / SNMP общие коды состояния (часто совпадают с globalSystemStatus и др.)
DELL_STATUS_TEXT: dict[int, str] = {
    1: "Other",
    2: "Unknown",
    3: "OK",
    4: "Non-Critical",
    5: "Critical",
    6: "Non-Recoverable",
}

# Тип RAID (virtualDisk) — типичные значения Dell PERC MIB (могут отличаться по прошивке)
RAID_TYPE_TEXT: dict[int, str] = {
    0: "Unknown",
    1: "RAID-0",
    2: "RAID-1",
    3: "RAID-5",
    4: "RAID-6",
    5: "RAID-1+0",
    6: "RAID-5+0",
    7: "RAID-6+0",
    8: "Concatenated",
}


def _safe_value(value: Any) -> str:
    if hasattr(value, "asOctets"):
        try:
            raw = bytes(value.asOctets()).rstrip(b"\x00")
            if raw and all(32 <= b <= 126 for b in raw):
                return raw.decode("utf-8", errors="replace").strip()
            return raw.hex()
        except Exception:
            return str(value)
    text = str(value).strip()
    return text.replace("\x00", "")


def _status_text(raw: str) -> str:
    try:
        code = int(raw)
    except ValueError:
        return raw or "—"
    return DELL_STATUS_TEXT.get(code, f"Code {code}")


def _raid_type_text(raw: str) -> str:
    try:
        code = int(raw)
    except ValueError:
        return raw or "—"
    return RAID_TYPE_TEXT.get(code, f"Code {code}")


def snmp_walk_column(
    host: str,
    port: int,
    community: str,
    column_oid: str,
    timeout_s: float,
    retries: int,
    max_rows: int = 512,
) -> dict[str, str]:
    """
    Обход одной колонки таблицы: возвращает {суффикс_индекса: строковое значение}.
    """
    engine = SnmpEngine()
    auth = CommunityData(community, mpModel=1)
    transport = UdpTransportTarget((host, port), timeout=timeout_s, retries=retries)
    context = ContextData()

    prefix = column_oid.rstrip(".")
    prefix_dot = prefix + "."

    out: dict[str, str] = {}
    count = 0
    last_error: str | None = None

    for error_indication, error_status, error_index, var_binds in nextCmd(
        engine,
        auth,
        transport,
        context,
        ObjectType(ObjectIdentity(column_oid)),
        lexicographicMode=False,
    ):
        if error_indication:
            last_error = str(error_indication)
            break
        if error_status:
            idx = error_index and error_index - 1 or 0
            last_error = f"{error_status.prettyPrint()} at {idx}"
            break

        for name, val in var_binds:
            oid_str = str(name)
            if not oid_str.startswith(prefix_dot):
                return out
            suffix = oid_str[len(prefix_dot) :]
            out[suffix] = _safe_value(val)
            count += 1
            if count >= max_rows:
                return out

    if last_error and not out:
        raise RuntimeError(last_error)
    return out


def merge_table(columns: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    """Объединяет несколько колонок по общему суффиксу индекса."""
    all_suffixes: set[str] = set()
    for col in columns.values():
        all_suffixes.update(col.keys())
    rows: list[dict[str, Any]] = []
    for suffix in sorted(all_suffixes, key=_sort_key):
        row: dict[str, Any] = {"index": suffix}
        for name, col in columns.items():
            row[name] = col.get(suffix, "")
        rows.append(row)
    return rows


def _sort_key(suffix: str) -> tuple:
    parts: list[int] = []
    for p in suffix.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def collect(
    host: str,
    port: int,
    community: str,
    timeout_s: float,
    retries: int,
) -> dict[str, Any]:
    # Physical disks (Dell Storage MIB — пример для iDRAC 8/9)
    pd_status_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.4"
    pd_model_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.6"
    pd_serial_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.10"
    pd_size_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.130.4.1.11"

    # Virtual disks (RAID logical volumes)
    vd_status_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.4"
    vd_size_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.6"
    vd_raid_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.140.1.1.13"

    # RAID controllers
    ctl_status_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.130.1.1.5"
    ctl_model_oid = "1.3.6.1.4.1.674.10892.5.5.1.20.130.1.1.2"

    errors: list[str] = []

    def walk_safe(oid: str) -> dict[str, str]:
        try:
            return snmp_walk_column(host, port, community, oid, timeout_s, retries)
        except Exception as exc:
            errors.append(f"{oid}: {exc}")
            return {}

    pd_cols = {
        "status_raw": walk_safe(pd_status_oid),
        "model": walk_safe(pd_model_oid),
        "serial_number": walk_safe(pd_serial_oid),
        "size_raw": walk_safe(pd_size_oid),
    }
    vd_cols = {
        "status_raw": walk_safe(vd_status_oid),
        "size_raw": walk_safe(vd_size_oid),
        "raid_type_raw": walk_safe(vd_raid_oid),
    }
    ctl_cols = {
        "status_raw": walk_safe(ctl_status_oid),
        "model": walk_safe(ctl_model_oid),
    }

    physical_disks = []
    for row in merge_table(pd_cols):
        if not any(str(row.get(k)) for k in ("status_raw", "model", "serial_number", "size_raw")):
            continue
        physical_disks.append(
            {
                "index": row["index"],
                "status": _status_text(str(row.get("status_raw", ""))),
                "status_code": row.get("status_raw", ""),
                "model": row.get("model", ""),
                "serial_number": row.get("serial_number", ""),
                "size": row.get("size_raw", ""),
            }
        )

    virtual_disks = []
    for row in merge_table(vd_cols):
        if not any(str(row.get(k)) for k in ("status_raw", "size_raw", "raid_type_raw")):
            continue
        virtual_disks.append(
            {
                "index": row["index"],
                "status": _status_text(str(row.get("status_raw", ""))),
                "status_code": row.get("status_raw", ""),
                "raid_type": _raid_type_text(str(row.get("raid_type_raw", ""))),
                "raid_type_code": row.get("raid_type_raw", ""),
                "size": row.get("size_raw", ""),
            }
        )

    controllers = []
    for row in merge_table(ctl_cols):
        if not any(str(row.get(k)) for k in ("status_raw", "model")):
            continue
        controllers.append(
            {
                "index": row["index"],
                "status": _status_text(str(row.get("status_raw", ""))),
                "status_code": row.get("status_raw", ""),
                "model": row.get("model", ""),
            }
        )

    return {
        "host": host,
        "snmp_port": port,
        "physical_disks": physical_disks,
        "virtual_disks": virtual_disks,
        "controllers": controllers,
        "warnings": errors,
        "note": "Пустые списки на iDRAC6 — нормально; для R710/iDRAC6 используйте PERCCLI на ESXi или обновите iDRAC.",
    }


def print_table(data: dict[str, Any]) -> None:
    def block(title: str, rows: list[dict[str, Any]], keys: list[str]) -> None:
        print(f"\n=== {title} ===")
        if not rows:
            print("  (нет данных)")
            return
        for i, row in enumerate(rows, 1):
            print(f"  [{i}] index={row.get('index')}")
            for k in keys:
                if k in row and row[k] != "":
                    print(f"      {k}: {row[k]}")

    block("Controllers", data.get("controllers", []), ["model", "status", "status_code"])
    block("Physical disks", data.get("physical_disks", []), ["model", "serial_number", "size", "status", "status_code"])
    block("Virtual disks (RAID)", data.get("virtual_disks", []), ["raid_type", "size", "status", "status_code"])
    if data.get("warnings"):
        print("\n=== Walk errors ===")
        for w in data["warnings"]:
            print(f"  ! {w}")
    if data.get("note"):
        print(f"\nNote: {data['note']}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Dell iDRAC storage via SNMP v2c (Dell MIB)")
    parser.add_argument("--host", required=True, help="IP iDRAC")
    parser.add_argument("--community", required=True, help="SNMP v2c community")
    parser.add_argument("--port", type=int, default=161, help="SNMP UDP port (default 161)")
    parser.add_argument("--timeout", type=float, default=2.0, help="Timeout per request, seconds")
    parser.add_argument("--retries", type=int, default=1, help="SNMP retries")
    parser.add_argument("--format", choices=("json", "table"), default="json", help="Output format")
    args = parser.parse_args()

    try:
        result = collect(
            host=args.host,
            port=args.port,
            community=args.community,
            timeout_s=args.timeout,
            retries=args.retries,
        )
    except Exception as exc:
        print(f"Ошибка SNMP: {exc}", file=sys.stderr)
        print(
            "Проверьте: SNMP включён на iDRAC, community, firewall, и что это не iDRAC6 без этих таблиц.",
            file=sys.stderr,
        )
        return 1

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_table(result)

    # Ненулевой код, если вообще ничего не собрали (часто таймаут / неверный community / пустой MIB)
    if not result["physical_disks"] and not result["virtual_disks"] and not result["controllers"]:
        if result["warnings"]:
            return 2
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
