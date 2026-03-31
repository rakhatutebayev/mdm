#!/usr/bin/env python3
"""
Проверка доступности SNMP (те же вызовы, что у поллера агента: puresnmp).

Запуск из каталога proxy-agent:
  python3 -m tools.snmp_check --ip 192.168.1.10 -c public
  python3 -m tools.snmp_check --ip 192.168.1.10 -c public --walk 1.3.6.1.2.1.1
  python3 -m tools.snmp_check --device my-server --config /etc/nocko-agent/config.json
  python3 -m tools.snmp_check --all --config /etc/nocko-agent/config.json
  python3 -m tools.snmp_check --list-devices --config /etc/nocko-agent/config.json

Код выхода: 0 — все проверки OK, 1 — SNMP не отвечает / ошибка, 2 — аргументы или БД.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from typing import Any

from sqlmodel import select

from core.config import load_config
from core.database import Device, get_session, init_db

# Стандартные OID (MIB-II system) — достаточно, чтобы понять «идут ли данные»
DEFAULT_OIDS: list[tuple[str, str]] = [
    ("1.3.6.1.2.1.1.1.0", "sysDescr"),
    ("1.3.6.1.2.1.1.3.0", "sysUpTime"),
    ("1.3.6.1.2.1.1.5.0", "sysName"),
]


def _stderr(msg: str) -> None:
    print(msg, file=sys.stderr)


def _preview_value(val: Any, limit: int = 120) -> str:
    s = repr(val)
    return s if len(s) <= limit else s[: limit - 3] + "..."


def _oid_arg(oid: str):
    """Use x690 ObjectIdentifier when available, otherwise pass the raw string."""
    try:
        from x690.types import ObjectIdentifier

        return ObjectIdentifier(oid)
    except Exception:
        return oid


async def snmp_get_value(ip: str, oid: str, dev: Device) -> tuple[Any | None, str | None]:
    """Один GET; при ошибке (None, текст исключения)."""
    try:
        import puresnmp

        if dev.snmp_version == "3":
            auth = None
            priv = None
            if dev.snmp_v3_auth_key:
                auth = puresnmp.Auth(dev.snmp_v3_auth_key.encode(), "sha")
            if dev.snmp_v3_priv_key:
                priv = puresnmp.Priv(dev.snmp_v3_priv_key.encode(), "aes")
            client = puresnmp.Client(ip, puresnmp.V3(dev.snmp_v3_user, auth=auth, priv=priv))
        else:
            client = puresnmp.Client(ip, puresnmp.V2C(dev.snmp_community))
        val = await client.get(_oid_arg(oid))
        return val, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


async def snmp_walk_values(ip: str, base_oid: str, dev: Device) -> tuple[list[tuple[str, Any]] | None, str | None]:
    """Один WALK; при ошибке (None, текст исключения)."""
    try:
        import puresnmp

        if dev.snmp_version == "3":
            auth = None
            priv = None
            if dev.snmp_v3_auth_key:
                auth = puresnmp.Auth(dev.snmp_v3_auth_key.encode(), "sha")
            if dev.snmp_v3_priv_key:
                priv = puresnmp.Priv(dev.snmp_v3_priv_key.encode(), "aes")
            client = puresnmp.Client(ip, puresnmp.V3(dev.snmp_v3_user, auth=auth, priv=priv))
        else:
            client = puresnmp.Client(ip, puresnmp.V2C(dev.snmp_community))
        rows: list[tuple[str, Any]] = []
        async for row in client.bulkwalk([_oid_arg(base_oid)]):
            rows.append((str(row.oid), row.value))
        return rows, None
    except Exception as e:
        return None, f"{type(e).__name__}: {e}"


def _cli_device(
    ip: str,
    community: str,
    snmp_version: str,
    v3_user: str,
    v3_auth: str,
    v3_priv: str,
) -> Device:
    ver = "3" if snmp_version == "3" else "2c"
    return Device(
        ip=ip.strip(),
        device_id="__snmp_check__",
        profile_id=None,
        snmp_version=ver,
        snmp_community=(community or "public").strip() or "public",
        snmp_v3_user=(v3_user or "").strip(),
        snmp_v3_auth_key=(v3_auth or "").strip(),
        snmp_v3_priv_key=(v3_priv or "").strip(),
    )


async def probe_device_get(
    dev: Device,
    oids: list[tuple[str, str]],
) -> dict[str, Any]:
    """Проверить набор OID через GET; вернуть структуру для печати / --json."""
    t0 = time.perf_counter()
    results: list[dict[str, Any]] = []
    all_ok = True
    first_err: str | None = None

    for oid, name in oids:
        val, err = await snmp_get_value(dev.ip, oid, dev)
        ok = err is None and val is not None
        if not ok and first_err is None:
            first_err = err or "пустой ответ"
        if not ok:
            all_ok = False
        results.append(
            {
                "oid": oid,
                "name": name,
                "ok": ok,
                "error": err,
                "value_preview": None if val is None else _preview_value(val),
            }
        )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "operation": "get",
        "target": dev.ip,
        "device_id": dev.device_id,
        "snmp_version": dev.snmp_version,
        "ok": all_ok,
        "elapsed_ms": elapsed_ms,
        "results": results,
        "summary_error": None if all_ok else (first_err or "SNMP недоступен"),
    }


async def probe_device_walk(
    dev: Device,
    base_oids: list[str],
    row_limit: int,
) -> dict[str, Any]:
    """Проверить набор OID через WALK; вернуть структуру для печати / --json."""
    t0 = time.perf_counter()
    results: list[dict[str, Any]] = []
    all_ok = True
    first_err: str | None = None

    for base_oid in base_oids:
        rows, err = await snmp_walk_values(dev.ip, base_oid, dev)
        ok = err is None and rows is not None
        if not ok and first_err is None:
            first_err = err or "пустой ответ"
        if not ok:
            all_ok = False
        preview_rows: list[dict[str, str]] = []
        if rows:
            for oid, val in rows[:row_limit]:
                preview_rows.append(
                    {
                        "oid": oid,
                        "value_preview": _preview_value(val),
                    }
                )
        results.append(
            {
                "base_oid": base_oid,
                "ok": ok,
                "error": err,
                "rows_total": 0 if rows is None else len(rows),
                "rows_preview": preview_rows,
                "rows_truncated": bool(rows and len(rows) > row_limit),
            }
        )

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    return {
        "operation": "walk",
        "target": dev.ip,
        "device_id": dev.device_id,
        "snmp_version": dev.snmp_version,
        "ok": all_ok,
        "elapsed_ms": elapsed_ms,
        "results": results,
        "summary_error": None if all_ok else (first_err or "SNMP WALK недоступен"),
    }


def print_human(report: dict[str, Any], verbose: bool) -> None:
    did = report.get("device_id")
    prefix = f"[{did}] " if did and did != "__snmp_check__" else ""
    ip = report["target"]
    ver = report["snmp_version"]
    op = str(report.get("operation") or "get").upper()
    if report["ok"]:
        print(f"{prefix}OK  {ip}  SNMPv{ver}  {op}  ({report['elapsed_ms']} ms)")
    else:
        print(f"{prefix}FAIL {ip}  SNMPv{ver}  {op}  — {report.get('summary_error')}")

    if report.get("operation") == "walk":
        for r in report["results"]:
            status = "OK" if r["ok"] else "FAIL"
            line = f"  {status}  WALK  {r['base_oid']}"
            if r["ok"]:
                line += f"  rows={r.get('rows_total', 0)}"
            else:
                line += f"  ({r.get('error') or 'no data'})"
            print(line)
            if verbose or not report["ok"]:
                for row in r.get("rows_preview") or []:
                    print(f"    {row['oid']}  =  {row['value_preview']}")
                if r.get("rows_truncated"):
                    print(f"    ... +{int(r['rows_total']) - len(r.get('rows_preview') or [])} more")
        return

    if verbose or not report["ok"]:
        for r in report["results"]:
            status = "OK" if r["ok"] else "FAIL"
            line = f"  {status}  {r['name']}  {r['oid']}"
            if r["ok"] and r.get("value_preview") is not None:
                line += f"  =  {r['value_preview']}"
            elif not r["ok"]:
                line += f"  ({r.get('error') or 'no data'})"
            print(line)


async def run_checks(
    devices: list[Device],
    get_oids_raw: list[str],
    walk_oids_raw: list[str],
    use_default_get: bool,
    walk_limit: int,
    json_mode: bool,
    verbose: bool,
) -> int:
    get_oids: list[tuple[str, str]] = []
    if use_default_get:
        get_oids.extend(DEFAULT_OIDS)
    for raw in get_oids_raw:
        oid = raw.strip()
        if oid:
            get_oids.append((oid, oid))

    walk_oids = [raw.strip() for raw in walk_oids_raw if raw.strip()]

    reports: list[dict[str, Any]] = []
    exit_code = 0

    for dev in devices:
        device_reports: list[dict[str, Any]] = []
        if get_oids:
            device_reports.append(await probe_device_get(dev, get_oids))
        if walk_oids:
            device_reports.append(await probe_device_walk(dev, walk_oids, walk_limit))

        reports.extend(device_reports)
        if any(not rep["ok"] for rep in device_reports):
            exit_code = 1
        if not json_mode:
            for idx, rep in enumerate(device_reports):
                print_human(rep, verbose)
                if idx != len(device_reports) - 1:
                    print()
            if len(devices) > 1:
                print()

    if json_mode:
        print(json.dumps(reports, ensure_ascii=False, indent=2))

    return exit_code


def cmd_list_devices() -> int:
    with get_session() as s:
        rows = s.exec(select(Device).order_by(Device.device_id)).all()
    if not rows:
        print("В БД нет устройств.")
        return 0
    for d in rows:
        ver = d.snmp_version
        auth = "v3" if ver == "3" else f"community={d.snmp_community!r}"
        prof = d.profile_id or "—"
        print(f"{d.device_id}\t{d.ip}\tprofile={prof}\tSNMP {ver}\t{auth}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Проверка SNMP GET/WALK (как у NOCKO proxy-agent).",
    )
    p.add_argument(
        "--config",
        default=None,
        help="Путь к config.json агента (для БД и --device / --all). По умолчанию NOCKO_CONFIG или ./config.json",
    )
    src = p.add_mutually_exclusive_group(required=False)
    src.add_argument("--ip", help="IP устройства (без БД)")
    src.add_argument("--device", metavar="DEVICE_ID", help="device_id из локальной SQLite")
    src.add_argument("--all", action="store_true", help="Проверить все устройства из БД")
    src.add_argument("--list-devices", action="store_true", help="Список устройств из БД и выход")

    p.add_argument("-c", "--community", default="public", help="SNMPv2c community (с --ip)")
    p.add_argument(
        "--snmp-version",
        choices=("2c", "3"),
        default="2c",
        help="Версия SNMP для --ip",
    )
    p.add_argument("--v3-user", default="", help="SNMPv3 user (с --ip)")
    p.add_argument("--v3-auth", default="", help="SNMPv3 auth password")
    p.add_argument("--v3-priv", default="", help="SNMPv3 priv password")

    p.add_argument(
        "--oid",
        action="append",
        default=[],
        help="OID для SNMP GET (можно повторять). По умолчанию также идут sysDescr/sysUpTime/sysName.",
    )
    p.add_argument(
        "--walk",
        action="append",
        default=[],
        help="Базовый OID для SNMP WALK (можно повторять)",
    )
    p.add_argument(
        "--no-default-get",
        action="store_true",
        help="Не выполнять стандартные GET sysDescr/sysUpTime/sysName",
    )
    p.add_argument(
        "--walk-limit",
        type=int,
        default=20,
        help="Сколько строк WALK показывать в stdout/JSON preview (по умолчанию 20)",
    )
    p.add_argument("--json", action="store_true", help="Вывод в JSON")
    p.add_argument("-v", "--verbose", action="store_true", help="Всегда показывать значения OID")

    args = p.parse_args(argv)

    need_db = args.list_devices or args.device or args.all
    if args.ip and need_db:
        _stderr("Нельзя совмещать --ip с --device / --all / --list-devices")
        return 2

    if not args.ip and not need_db:
        p.print_help()
        _stderr("\nУкажите --ip, --device, --all или --list-devices.")
        return 2

    has_any_op = (not args.no_default_get) or bool(args.oid) or bool(args.walk)
    if not has_any_op:
        _stderr("Не выбрана ни одна SNMP-операция: используйте GET по умолчанию, --oid и/или --walk.")
        return 2
    if args.walk_limit <= 0:
        _stderr("--walk-limit должен быть > 0")
        return 2

    if need_db:
        from core.config import config as agent_cfg

        load_config(args.config)
        init_db(agent_cfg.local.db_path)

    if args.list_devices:
        return cmd_list_devices()

    devices: list[Device] = []

    if args.ip:
        devices.append(
            _cli_device(
                args.ip,
                args.community,
                args.snmp_version,
                args.v3_user,
                args.v3_auth,
                args.v3_priv,
            )
        )
    elif args.all:
        with get_session() as s:
            devices = list(s.exec(select(Device)).all())
        if not devices:
            _stderr("В БД нет устройств.")
            return 2
    else:
        did = (args.device or "").strip()
        with get_session() as s:
            dev = s.exec(select(Device).where(Device.device_id == did)).first()
        if not dev:
            _stderr(f"Устройство {did!r} не найдено в БД.")
            return 2
        devices = [dev]

    try:
        return asyncio.run(
            run_checks(
                devices,
                args.oid,
                args.walk,
                not args.no_default_get,
                args.walk_limit,
                args.json,
                args.verbose,
            )
        )
    except ModuleNotFoundError as e:
        if e.name == "puresnmp" or (getattr(e, "msg", "") and "puresnmp" in str(e)):
            _stderr("Нет пакета puresnmp. Установите зависимости агента: pip install -r requirements.txt")
            return 2
        raise
    except KeyboardInterrupt:
        _stderr("Прервано.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
