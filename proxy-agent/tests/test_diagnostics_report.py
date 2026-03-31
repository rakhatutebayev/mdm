"""Самодиагностика: отчёт и строка HEALTH без живого MQTT/SNMP."""
from __future__ import annotations

import json
from pathlib import Path

from core.config import load_config
from core.database import Device, init_db
from core.diagnostics_report import (
    build_diagnostics_report,
    health_log_interval_sec,
    health_log_line,
)
from sqlmodel import Session, create_engine


def test_health_log_line_shape(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "config.json"
    db = tmp_path / "agent.db"
    cfg.write_text(
        json.dumps({"db_path": str(db), "data_dir": str(tmp_path)}),
        encoding="utf-8",
    )
    load_config(str(cfg))
    init_db(str(db))

    engine = create_engine(f"sqlite:///{db}")
    with Session(engine) as s:
        s.add(
            Device(
                ip="10.0.0.1",
                device_id="d1",
                profile_id=None,
                snmp_community="public",
            )
        )
        s.commit()

    line = health_log_line()
    assert line.startswith("HEALTH_SUMMARY ")
    assert "mqtt=" in line
    assert "dev=1" in line
    assert "broker=" in line


def test_build_diagnostics_report_jsonable(tmp_path: Path):
    cfg = tmp_path / "config.json"
    db = tmp_path / "agent.db"
    cfg.write_text(
        json.dumps({"db_path": str(db), "data_dir": str(tmp_path)}),
        encoding="utf-8",
    )
    load_config(str(cfg))
    init_db(str(db))

    r = build_diagnostics_report()
    json.dumps(r)
    assert r["schema"] == "nocko_agent_diagnostics/1"
    assert "mqtt" in r and "summary" in r
    assert r["devices_total"] == 0


def test_health_log_interval_env(monkeypatch):
    monkeypatch.delenv("NOCKO_HEALTH_LOG_SEC", raising=False)
    assert health_log_interval_sec() == 300
    monkeypatch.setenv("NOCKO_HEALTH_LOG_SEC", "0")
    assert health_log_interval_sec() == 0
    monkeypatch.setenv("NOCKO_HEALTH_LOG_SEC", "120")
    assert health_log_interval_sec() == 120
