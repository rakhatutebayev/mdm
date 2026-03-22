"""
Bootstrap HTTP client for NOCKO Proxy Agent.

Handles all HTTPS operations (one-time bootstrap and config refresh).
Uses mTLS after initial registration (client certificate).

Endpoints (proxy_agent_tz.md Section 2.7.1):
  POST  /api/v1/agent/register    — enroll with one-time token
  GET   /api/v1/agent/config      — fetch server-managed config
  GET   /api/v1/agent/items       — fetch items for a profile
"""
from __future__ import annotations

import json
import ssl
from pathlib import Path
from typing import Any

import httpx

from core.config import config, ServerConfig
from core.database import kv_get, kv_set, ConfigVersion, get_session
from core.logger import log

_REGISTER_PATH = "/api/v1/agent/register"
_CONFIG_PATH = "/api/v1/agent/config"
_ITEMS_PATH = "/api/v1/agent/items"


def apply_kv_identity_to_server_config() -> None:
    """
    Copy agent_id, tenant_id, site_id, broker_url from agent_config KV into
    config.server so MQTT envelopes and trap events include correct ids.
    """
    sc = config.server
    aid = kv_get("agent_id", "").strip()
    tid = kv_get("tenant_id", "").strip()
    sid = kv_get("site_id", "").strip()
    br = kv_get("broker_url", "").strip()
    if aid:
        sc.agent_id = aid
    if tid:
        sc.tenant_id = tid
    if sid:
        sc.site_id = sid
    if br:
        sc.broker_url = br


def _make_client(use_client_cert: bool = False) -> httpx.Client:
    """Build httpx client, optionally with mTLS client certificate."""
    kwargs: dict[str, Any] = {"base_url": config.local.mdm_url, "timeout": 30.0}

    ca = config.mdm_trust_ca_path
    if ca:
        kwargs["verify"] = str(ca)
        log.debug(f"HTTPS verify using trust anchor: {ca}")
    else:
        kwargs["verify"] = True

    headers: dict[str, str] = {}
    if use_client_cert:
        cert_path = config.client_cert
        key_path = config.client_key
        if cert_path.exists() and key_path.exists():
            kwargs["cert"] = (str(cert_path), str(key_path))
        else:
            token = kv_get("auth_token", "").strip()
            if token:
                headers["Authorization"] = f"Bearer {token}"
                log.debug("Using Bearer auth_token for MDM API (no client cert yet)")
            else:
                log.warning("Client cert not found and no auth_token — authenticated MDM calls may fail")

    if headers:
        kwargs["headers"] = headers

    return httpx.Client(**kwargs)


# ──────────────────────────────────────────────────────────────────────────────
# Registration
# ──────────────────────────────────────────────────────────────────────────────
def register(enrollment_token: str) -> dict:
    """
    POST /api/v1/agent/register with enrollment token.
    On success: saves agent_id, tenant_id, broker_url, client cert to disk.
    Returns the response dict.
    """
    payload = {
        "enrollment_token": enrollment_token,
        "hostname": _get_hostname(),
        "version": kv_get("agent_version", "1.0.0"),
    }

    log.info("Registering agent with MDM...")
    with _make_client(use_client_cert=False) as client:
        resp = client.post(_REGISTER_PATH, json=payload)
        resp.raise_for_status()
        data = resp.json()

    # Persist registration data
    kv_set("agent_id", data.get("agent_id", ""))
    kv_set("tenant_id", data.get("tenant_id", ""))
    kv_set("site_id", data.get("site_id", ""))
    kv_set("broker_url", data.get("broker_url", ""))
    if data.get("auth_token"):
        kv_set("auth_token", str(data["auth_token"]))
    kv_set("registered", "true")

    # Write client certificate if provided
    if "client_cert" in data and "client_key" in data:
        _save_certs(data["client_cert"], data["client_key"])

    apply_kv_identity_to_server_config()

    log.info(f"Registration successful. agent_id={data.get('agent_id')}")
    return data


# ──────────────────────────────────────────────────────────────────────────────
# Config fetch
# ──────────────────────────────────────────────────────────────────────────────
def fetch_config() -> ServerConfig:
    """
    GET /api/v1/agent/config — fetch full server-managed configuration.
    Updates config.server in-place and persists to agent_config KV store.
    """
    log.info("Fetching server config from MDM...")
    with _make_client(use_client_cert=True) as client:
        resp = client.get(_CONFIG_PATH)
        resp.raise_for_status()
        data = resp.json()

    # Map response fields to ServerConfig
    sc = config.server
    # Start from KV (registration snapshot), then overlay HTTP (authoritative for broker_url/broker_port)
    apply_kv_identity_to_server_config()

    sc.heartbeat_interval = data.get("heartbeat_interval", sc.heartbeat_interval)
    sc.metrics_fast_interval = data.get("metrics_fast_interval", sc.metrics_fast_interval)
    sc.metrics_slow_interval = data.get("metrics_slow_interval", sc.metrics_slow_interval)
    sc.inventory_interval = data.get("inventory_interval", sc.inventory_interval)

    for key in ("agent_id", "tenant_id", "site_id", "broker_url"):
        val = data.get(key)
        if val is not None and str(val).strip() != "":
            setattr(sc, key, str(val))
    if data.get("broker_port") is not None:
        try:
            sc.broker_port = int(data["broker_port"])
        except (TypeError, ValueError):
            pass

    # Keep KV in sync so later calls are consistent
    if data.get("broker_url"):
        kv_set("broker_url", str(data["broker_url"]).strip())

    # Persist raw config to config_versions table
    with get_session() as session:
        version = data.get("config_version", "unknown")
        session.add(ConfigVersion(
            version=version,
            config_json=json.dumps(data),
        ))
        session.commit()
        log.info(f"Server config applied (version={version})")

    return sc


# ──────────────────────────────────────────────────────────────────────────────
# Items (profile metric keys)
# ──────────────────────────────────────────────────────────────────────────────
def fetch_items(profile_id: str) -> list[dict]:
    """
    GET /api/v1/agent/items?profile_id=X
    Returns list of item dicts with keys: key, value_type, poll_class, interval_sec, output_mapping
    """
    log.info(f"Fetching items for profile {profile_id}...")
    with _make_client(use_client_cert=True) as client:
        resp = client.get(_ITEMS_PATH, params={"profile_id": profile_id})
        resp.raise_for_status()
        items = resp.json()
    log.info(f"Fetched {len(items)} items for profile {profile_id}")
    return items


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _get_hostname() -> str:
    import socket
    try:
        return socket.getfqdn()
    except Exception:
        return "unknown"


def _save_certs(cert_pem: str, key_pem: str) -> None:
    cert_dir = config.cert_dir
    cert_dir.mkdir(parents=True, exist_ok=True)
    (cert_dir / "client.crt").write_text(cert_pem, encoding="utf-8")
    (cert_dir / "client.key").write_text(key_pem, encoding="utf-8")
    # Restrict key permissions
    import os
    os.chmod(cert_dir / "client.key", 0o600)
    log.info(f"Client certificate saved to {cert_dir}")
