"""CLI smoke tests for tools.snmp_check (no live SNMP)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools import snmp_check


def test_snmp_check_no_target_exit_2():
    assert snmp_check.main([]) == 2


def test_snmp_check_help_exits_0():
    with pytest.raises(SystemExit) as e:
        snmp_check.main(["--help"])
    assert e.value.code == 0


def test_list_devices_empty_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps({"db_path": str(tmp_path / "agent.db"), "data_dir": str(tmp_path)}),
        encoding="utf-8",
    )
    code = snmp_check.main(["--list-devices", "--config", str(cfg)])
    assert code == 0


def test_device_missing_exit_2(tmp_path: Path):
    cfg = tmp_path / "config.json"
    db = tmp_path / "agent.db"
    cfg.write_text(
        json.dumps({"db_path": str(db), "data_dir": str(tmp_path)}),
        encoding="utf-8",
    )
    code = snmp_check.main(["--device", "nope", "--config", str(cfg)])
    assert code == 2


def test_no_default_get_without_ops_exit_2():
    assert snmp_check.main(["--ip", "192.0.2.10", "--no-default-get"]) == 2


def test_walk_args_are_forwarded(monkeypatch: pytest.MonkeyPatch):
    seen: dict[str, object] = {}

    async def fake_run_checks(devices, get_oids_raw, walk_oids_raw, use_default_get, walk_limit, json_mode, verbose):
        seen["devices"] = devices
        seen["get_oids_raw"] = get_oids_raw
        seen["walk_oids_raw"] = walk_oids_raw
        seen["use_default_get"] = use_default_get
        seen["walk_limit"] = walk_limit
        seen["json_mode"] = json_mode
        seen["verbose"] = verbose
        return 0

    monkeypatch.setattr(snmp_check, "run_checks", fake_run_checks)

    code = snmp_check.main(
        [
            "--ip",
            "192.0.2.10",
            "-c",
            "public",
            "--walk",
            "1.3.6.1.2.1.1",
            "--no-default-get",
            "--walk-limit",
            "7",
            "--json",
        ]
    )

    assert code == 0
    assert seen["walk_oids_raw"] == ["1.3.6.1.2.1.1"]
    assert seen["use_default_get"] is False
    assert seen["walk_limit"] == 7
    assert seen["json_mode"] is True
