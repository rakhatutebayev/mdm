"""
Unit tests for NOCKO Proxy Agent core modules.
Uses pytest + in-memory SQLite (no external dependencies).

Run:
  cd proxy-agent && python -m pytest tests/ -v
"""
from __future__ import annotations

import json
import os
import sys
import time
import tempfile
import pytest

# Ensure proxy-agent/ is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ──────────────────────────────────────────────────────────────────────────────
# test_config.py
# ──────────────────────────────────────────────────────────────────────────────
class TestConfig:
    def test_defaults(self, tmp_path):
        """Config loads defaults when config.json is absent."""
        from core.config import load_config
        cfg = load_config(config_path=tmp_path / "nonexistent.json")
        assert cfg.local.listen_port == 8443
        assert cfg.local.log_level == "INFO"
        assert cfg.server.heartbeat_interval == 60

    def test_load_from_file(self, tmp_path):
        """Config reads local fields from JSON file."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({
            "listen_port": 9999,
            "log_level": "DEBUG",
            "mdm_url": "https://test.nocko.com",
        }))
        from core.config import load_config
        cfg = load_config(config_path=cfg_file)
        assert cfg.local.listen_port == 9999
        assert cfg.local.log_level == "DEBUG"
        assert cfg.local.mdm_url == "https://test.nocko.com"

    def test_server_defaults_unchanged(self, tmp_path):
        """Server config is NOT loaded from local config.json."""
        cfg_file = tmp_path / "config.json"
        cfg_file.write_text(json.dumps({"listen_port": 1234}))
        from core.config import load_config
        cfg = load_config(config_path=cfg_file)
        # Server config should stay at defaults
        assert cfg.server.metrics_fast_interval == 60
        assert cfg.server.metrics_slow_interval == 300


# ──────────────────────────────────────────────────────────────────────────────
# test_queue.py
# ──────────────────────────────────────────────────────────────────────────────
class TestQueue:
    @pytest.fixture(autouse=True)
    def fresh_db(self, tmp_path, monkeypatch):
        """Initialize a fresh in-memory SQLite DB for each test."""
        db_path = str(tmp_path / "test.db")
        # Patch config singleton db_path
        from core import database
        database.init_db(db_path)
        yield

    def test_enqueue_and_pending(self):
        from core.queue import enqueue, get_pending, queue_size
        enqueue("metrics.fast", {"foo": 1}, device_id="dev-1")
        enqueue("metrics.fast", {"bar": 2}, device_id="dev-1")
        assert queue_size("pending") == 2
        pending = get_pending(limit=10)
        assert len(pending) == 2

    def test_mark_sent(self):
        from core.queue import enqueue, mark_sent, queue_size
        item_id = enqueue("events", {"x": "y"})
        mark_sent(item_id)
        assert queue_size("pending") == 0
        assert queue_size("sent") == 1

    def test_mark_failed_five_attempts(self):
        from core.queue import enqueue, mark_failed, queue_size
        item_id = enqueue("metrics.fast", {})
        for _ in range(5):
            mark_failed(item_id)
        assert queue_size("failed") == 1
        assert queue_size("pending") == 0

    def test_ttl_drops_stale_metrics(self):
        """Metrics older than 24h should be filtered from pending."""
        from core import queue as q
        item_id = q.enqueue("metrics.fast", {"stale": True})
        # Backdate enqueue_timestamp inside the same session engine
        with q.get_session() as s:
            item = s.get(q.QueueItem, item_id)
            item.enqueue_timestamp = int(time.time()) - 90000  # > 24h
            s.commit()
        pending = q.get_pending(limit=100)
        ids = [p.id for p in pending]
        assert item_id not in ids, f"Stale metric (id={item_id}) should be dropped; got ids={ids}"

    def test_events_not_dropped_by_ttl(self):
        """Events should not be subject to metrics TTL."""
        from core import queue as q
        item_id = q.enqueue("events", {"important": True})
        with q.get_session() as s:
            item = s.get(q.QueueItem, item_id)
            item.enqueue_timestamp = int(time.time()) - 90000
            s.commit()
        pending = q.get_pending(limit=100)
        assert any(p.id == item_id for p in pending), "Events should survive TTL filter"

    def test_prune_sent(self):
        from core.queue import enqueue, mark_sent, prune_sent, queue_size
        from core.database import QueueItem, get_session
        from datetime import datetime, timedelta
        item_id = enqueue("metrics.fast", {})
        mark_sent(item_id)
        # Backdate updated_at so it is older than the prune window
        with get_session() as s:
            item = s.get(QueueItem, item_id)
            item.updated_at = datetime.utcnow() - timedelta(hours=72)
            s.commit()
        pruned = prune_sent(older_than_hours=48)
        assert pruned >= 1  # at least our item was pruned


# ──────────────────────────────────────────────────────────────────────────────
# test_payload.py
# ──────────────────────────────────────────────────────────────────────────────
class TestPayload:
    """Validate Section 7 payload envelope structure."""

    def _envelope(self, payload_type: str, records: list) -> dict:
        return {
            "schema_version": "1.0",
            "tenant_id": "1",
            "agent_id": "42",
            "sent_at": int(time.time()),
            "payload_type": payload_type,
            "records": records,
        }

    def test_envelope_has_required_fields(self):
        env = self._envelope("metrics", [])
        env["metrics_tier"] = "fast"
        required = ["schema_version", "tenant_id", "agent_id", "sent_at", "payload_type", "records"]
        for field in required:
            assert field in env, f"Missing field: {field}"
        assert env["payload_type"] == "metrics"
        assert env["metrics_tier"] in ("fast", "slow")

    def test_metrics_record_has_required_fields(self):
        record = {
            "device_uid": "abc-123",
            "clock": int(time.time()),
            "enqueue_ts": int(time.time()),
            "data": {"cpu.util": 45.2},
        }
        env = self._envelope("metrics", [record])
        env["metrics_tier"] = "slow"
        assert env["records"][0]["device_uid"] == "abc-123"
        assert "data" in env["records"][0]

    def test_inventory_record_has_vendor_model(self):
        record = {
            "device_uid": "switch-01",
            "clock": int(time.time()),
            "data": {"vendor": "Cisco", "model": "C9300", "serial": "FXS123"},
        }
        env = self._envelope("inventory", [record])
        data = env["records"][0]["data"]
        assert "vendor" in data and "model" in data

    def test_event_record_has_severity(self):
        record = {
            "device_uid": "srv-01",
            "clock": int(time.time()),
            "event_type": "trap",
            "source": "1.3.6.1.4.1.674",
            "severity": "warning",
            "code": "TEMP_HIGH",
            "message": "Temperature exceeded threshold",
            "item_key": None,
        }
        env = self._envelope("events", [record])
        assert env["records"][0]["severity"] in ("info", "warning", "critical")

    def test_heartbeat_record(self):
        record = {
            "clock": int(time.time()),
            "status": "ok",
            "queue_size": 0,
            "agent_version": "1.0.0",
        }
        env = self._envelope("heartbeat", [record])
        assert env["payload_type"] == "heartbeat"


# ──────────────────────────────────────────────────────────────────────────────
# test_database.py
# ──────────────────────────────────────────────────────────────────────────────
class TestDatabase:
    @pytest.fixture(autouse=True)
    def fresh_db(self, tmp_path):
        from core.database import init_db
        init_db(str(tmp_path / "test.db"))
        yield

    def test_kv_set_and_get(self):
        from core.database import kv_set, kv_get
        kv_set("test_key", "test_value")
        assert kv_get("test_key") == "test_value"

    def test_kv_overwrite(self):
        from core.database import kv_set, kv_get
        kv_set("k", "v1")
        kv_set("k", "v2")
        assert kv_get("k") == "v2"

    def test_kv_default(self):
        from core.database import kv_get
        assert kv_get("nonexistent", "fallback") == "fallback"

    def test_device_create(self):
        from core.database import Device, get_session
        from sqlmodel import select
        with get_session() as s:
            s.add(Device(ip="192.168.1.1", device_id="test-uid"))
            s.commit()
        with get_session() as s:
            result = s.exec(select(Device).where(Device.device_id == "test-uid")).first()
            assert result is not None
            assert result.ip == "192.168.1.1"

    def test_device_unique_device_id(self):
        from core.database import Device, get_session
        import sqlalchemy.exc
        with get_session() as s:
            s.add(Device(ip="192.168.1.1", device_id="dup-uid"))
            s.commit()
        with pytest.raises(Exception):
            with get_session() as s:
                s.add(Device(ip="192.168.1.2", device_id="dup-uid"))
                s.commit()

    def test_audit_log(self):
        from core.database import AuditLog, get_session
        from sqlmodel import select
        with get_session() as s:
            s.add(AuditLog(action="test_action", details='{"key":"value"}'))
            s.commit()
        with get_session() as s:
            rows = s.exec(select(AuditLog)).all()
            assert len(rows) == 1
            assert rows[0].action == "test_action"


# ──────────────────────────────────────────────────────────────────────────────
# MQTT broker URL (WSS / TCP)
# ──────────────────────────────────────────────────────────────────────────────
class TestZabbixImportYaml:
    def test_yaml_minimal_export(self):
        from core.zabbix_import import parse_zabbix_template_bytes

        yaml_text = """
zabbix_export:
  version: '6.0'
  templates:
    - name: Test SNMP Template
      items:
        - name: CPU Load
          type: SNMP_AGENT
          snmp_oid: 1.3.6.1.4.1.2021.10.1.3.1
          key: system.cpu.load
          delay: 1m
          value_type: FLOAT
          units: '%'
"""
        pid, pname, mapping, warns = parse_zabbix_template_bytes(
            yaml_text.encode("utf-8"), "t.yml"
        )
        assert pid == "test_snmp_template"
        assert pname == "Test SNMP Template"
        assert len(mapping) == 1
        assert mapping[0]["source_oid"] == "1.3.6.1.4.1.2021.10.1.3.1"
        assert mapping[0]["target_key"] == "system.cpu.load"
        assert mapping[0]["data_type"] == "float"

    def test_yaml_template_as_single_dict_not_list(self):
        """PyYAML loads one template as mapping under templates:, not []."""
        from core.zabbix_import import parse_zabbix_template_bytes

        yaml_text = """
zabbix_export:
  version: '6.0'
  templates:
    name: Dell iDRAC YAML
    items:
      - name: Test
        snmp_oid: 1.3.6.1.2.1.1.3.0
        key: system.uptime
        delay: 60s
"""
        pid, pname, mapping, _ = parse_zabbix_template_bytes(
            yaml_text.encode("utf-8"), "t.yml"
        )
        assert pid == "dell_idrac_yaml"
        assert len(mapping) == 1
        assert mapping[0]["source_oid"] == "1.3.6.1.2.1.1.3.0"

    def test_yaml_discovery_item_prototypes(self):
        from core.zabbix_import import parse_zabbix_template_bytes

        yaml_text = """
zabbix_export:
  templates:
    - name: With LLD
      discovery_rules:
        - name: iface
          item_prototypes:
            - key: net.if.in[{#SNMPVALUE}]
              snmp_oid: 1.3.6.1.2.1.2.2.1.10.{#SNMPINDEX}
              delay: 1m
"""
        _, _, mapping, _ = parse_zabbix_template_bytes(yaml_text.encode(), "x.yml")
        assert len(mapping) == 1
        assert "1.3.6.1.2.1.2.2.1.10" in mapping[0]["source_oid"]


class TestProfileReadiness:
    def test_pick_probe_oid_skips_lld_macros(self):
        from core.profile_readiness import pick_probe_oid

        m = [
            {"source_oid": "1.3.6.1.2.1.1.{#SNMPINDEX}", "key": "x", "poll_class": "fast"},
            {"source_oid": "1.3.6.1.2.1.1.3.0", "key": "uptime", "poll_class": "slow"},
        ]
        assert pick_probe_oid(m) == "1.3.6.1.2.1.1.3.0"


class TestParseMqttBrokerUrl:
    def test_wss_default_path_and_port(self):
        from core.mqtt_client import _parse_mqtt_broker_url
        p = _parse_mqtt_broker_url("wss://mdm.example.com/mqtt")
        assert p["transport"] == "websockets"
        assert p["host"] == "mdm.example.com"
        assert p["port"] == 443
        assert p["path"] == "/mqtt"
        assert p["use_tls"] is True

    def test_mqtt_tcp(self):
        from core.mqtt_client import _parse_mqtt_broker_url
        p = _parse_mqtt_broker_url("mqtt://broker.lan:1883")
        assert p["transport"] == "tcp"
        assert p["host"] == "broker.lan"
        assert p["port"] == 1883
        assert p["use_tls"] is False
