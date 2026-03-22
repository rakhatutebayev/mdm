"""
Integration tests for the Portal Backend Agent Layer.
Uses pytest + FastAPI TestClient with in-memory SQLite.

Run:
  cd backend && python -m pytest tests/test_agent_portal.py -v
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

# Override DB URL to in-memory SQLite before importing app
import os
os.environ["DATABASE_URL"] = "sqlite:///:memory:"


@pytest.fixture(scope="module")
def client():
    """Create a test FastAPI client with an in-memory SQLite."""
    from main import app
    from database import Base, get_db
    from agent_models import Agent, AgentDevice, Profile, Template, Item, Alert

    # Create all tables in memory
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(bind=engine)
    Base.metadata.create_all(engine)

    # Dependency override
    def override_get_db():
        db = TestingSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


TENANT = {"X-Tenant-Id": "1"}


# ── helper: seed data ─────────────────────────────────────────────────────────
@pytest.fixture(scope="module")
def seeded(client: TestClient):
    """Returns dict of created resource IDs."""
    # Create agent via registration endpoint
    r = client.post("/api/v1/agent/register", json={
        "tenant_id": 1,
        "hostname": "test-agent-01",
        "ip": "10.0.0.1",
        "version": "1.0.0",
        "enrollment_token": "test-token",
    })
    assert r.status_code in (200, 201, 409), r.text

    # Fetch agent from portal
    r = client.get("/api/v1/portal/agents", headers=TENANT)
    agents = r.json()
    agent_id = agents[0]["id"] if agents else None

    # Create profile
    r = client.post("/api/v1/portal/profiles", headers=TENANT, json={
        "name": "Dell iDRAC7", "vendor": "Dell", "version": "1.0.0",
        "description": "Dell iDRAC7 SNMP profile",
    })
    assert r.status_code == 201
    profile_id = r.json()["id"]

    # Create template
    r = client.post(f"/api/v1/portal/profiles/{profile_id}/templates", headers=TENANT, json={
        "name": "CPU Metrics",
    })
    assert r.status_code == 201
    template_id = r.json()["id"]

    # Create item
    r = client.post(f"/api/v1/portal/templates/{template_id}/items", headers=TENANT, json={
        "key": "cpu.util", "name": "CPU Utilization",
        "value_type": "uint", "poll_class": "fast", "interval_sec": 60,
    })
    assert r.status_code == 201
    item_id = r.json()["id"]

    return {
        "agent_id": agent_id,
        "profile_id": profile_id,
        "template_id": template_id,
        "item_id": item_id,
    }


# ─── Agents ──────────────────────────────────────────────────────────────────
class TestAgents:
    def test_list_agents(self, client, seeded):
        r = client.get("/api/v1/portal/agents", headers=TENANT)
        assert r.status_code == 200
        data = r.json()
        assert isinstance(data, list)

    def test_require_tenant_header(self, client):
        r = client.get("/api/v1/portal/agents")
        assert r.status_code == 401

    def test_update_agent_status(self, client, seeded):
        agent_id = seeded["agent_id"]
        if not agent_id:
            pytest.skip("No agent seeded")
        r = client.patch(
            f"/api/v1/portal/agents/{agent_id}/status",
            headers=TENANT,
            json={"admin_status": "disabled"},
        )
        assert r.status_code == 200
        assert r.json()["admin_status"] == "disabled"
        # Restore
        client.patch(f"/api/v1/portal/agents/{agent_id}/status", headers=TENANT,
                     json={"admin_status": "active"})

    def test_invalid_admin_status(self, client, seeded):
        agent_id = seeded["agent_id"]
        if not agent_id:
            pytest.skip("No agent seeded")
        r = client.patch(
            f"/api/v1/portal/agents/{agent_id}/status",
            headers=TENANT,
            json={"admin_status": "invalid_value"},
        )
        assert r.status_code == 400


# ─── Profiles + Templates + Items ─────────────────────────────────────────────
class TestProfiles:
    def test_list_profiles(self, client, seeded):
        r = client.get("/api/v1/portal/profiles", headers=TENANT)
        assert r.status_code == 200
        profiles = r.json()
        assert any(p["id"] == seeded["profile_id"] for p in profiles)

    def test_list_templates(self, client, seeded):
        r = client.get(f"/api/v1/portal/profiles/{seeded['profile_id']}/templates", headers=TENANT)
        assert r.status_code == 200
        templates = r.json()
        assert len(templates) >= 1
        assert any(t["id"] == seeded["template_id"] for t in templates)

    def test_template_has_items(self, client, seeded):
        r = client.get(f"/api/v1/portal/profiles/{seeded['profile_id']}/templates", headers=TENANT)
        templates = r.json()
        tmpl = next(t for t in templates if t["id"] == seeded["template_id"])
        assert len(tmpl["items"]) >= 1
        assert tmpl["items"][0]["key"] == "cpu.util"

    def test_duplicate_key_conflict(self, client, seeded):
        """K-2: same key in same profile must return 409."""
        r = client.post(
            f"/api/v1/portal/templates/{seeded['template_id']}/items",
            headers=TENANT,
            json={"key": "cpu.util", "value_type": "uint"},
        )
        assert r.status_code == 409

    def test_create_second_template_unique_key(self, client, seeded):
        """K-2: same key on DIFFERENT profile is allowed."""
        # Create different profile
        r1 = client.post("/api/v1/portal/profiles", headers=TENANT,
                         json={"name": "Other Profile", "vendor": "HP"})
        assert r1.status_code == 201
        p2_id = r1.json()["id"]

        r2 = client.post(f"/api/v1/portal/profiles/{p2_id}/templates", headers=TENANT,
                         json={"name": "Template 2"})
        t2_id = r2.json()["id"]

        r3 = client.post(f"/api/v1/portal/templates/{t2_id}/items", headers=TENANT,
                         json={"key": "cpu.util", "value_type": "uint"})
        assert r3.status_code == 201, "Same key allowed in different profile"


# ─── Alerts ──────────────────────────────────────────────────────────────────
class TestAlerts:
    def test_list_alerts_empty(self, client, seeded):
        r = client.get("/api/v1/portal/alerts", headers=TENANT)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_close_nonexistent_alert(self, client, seeded):
        r = client.post("/api/v1/portal/alerts/99999/close", headers=TENANT)
        assert r.status_code == 404

    def test_alerts_filter_active_only(self, client, seeded):
        r = client.get("/api/v1/portal/alerts?active_only=false", headers=TENANT)
        assert r.status_code == 200


# ─── Devices ──────────────────────────────────────────────────────────────────
class TestDevices:
    def test_list_devices(self, client, seeded):
        r = client.get("/api/v1/portal/devices", headers=TENANT)
        assert r.status_code == 200
        assert isinstance(r.json(), list)

    def test_get_nonexistent_device(self, client, seeded):
        r = client.get("/api/v1/portal/devices/99999", headers=TENANT)
        assert r.status_code == 404

    def test_history_bad_value_type(self, client, seeded):
        r = client.get(
            "/api/v1/portal/devices/1/history?item_id=1&value_type=bad_type",
            headers=TENANT,
        )
        assert r.status_code in (400, 404)


# ─── Commands ────────────────────────────────────────────────────────────────
class TestCommands:
    def test_issue_command_not_found(self, client, seeded):
        r = client.post(
            "/api/v1/portal/agents/99999/command",
            headers=TENANT,
            json={"command_type": "ping"},
        )
        assert r.status_code == 404

    def test_issue_command_ok(self, client, seeded):
        agent_id = seeded["agent_id"]
        if not agent_id:
            pytest.skip("No agent seeded")
        r = client.post(
            f"/api/v1/portal/agents/{agent_id}/command",
            headers=TENANT,
            json={"command_type": "ping", "payload": {}, "issued_by": "pytest"},
        )
        assert r.status_code == 200
        data = r.json()
        assert "command_id" in data
        assert data["status"] == "pending"

    def test_list_agent_commands(self, client, seeded):
        agent_id = seeded["agent_id"]
        if not agent_id:
            pytest.skip("No agent seeded")
        r = client.get(f"/api/v1/portal/agents/{agent_id}/commands", headers=TENANT)
        assert r.status_code == 200
        cmds = r.json()
        assert isinstance(cmds, list)
        assert any(c["command_type"] == "ping" for c in cmds)
