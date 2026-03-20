"""Local web console for Proxy Agent."""
from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from proxy_agent.main import (
    DEFAULT_CONFIG_PATH,
    build_payload,
    default_hostname,
    detect_primary_ip,
    load_config,
    normalize_server_url,
    post_ingest,
    save_config,
)
from proxy_agent.state import (
    DEFAULT_STATE_PATH,
    load_state,
    record_run_failure,
    record_run_start,
    record_run_success,
)


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>NOCKO Proxy Agent Console</title>
  <style>
    :root {
      --bg: #07111f;
      --panel: #0f1b2d;
      --panel-2: #13233a;
      --text: #e5edf8;
      --muted: #90a4bf;
      --line: #24364f;
      --blue: #3b82f6;
      --green: #22c55e;
      --red: #ef4444;
      --yellow: #f59e0b;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      padding: 24px;
      font-family: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      background: linear-gradient(180deg, #06101c 0%, #0a1525 100%);
      color: var(--text);
    }
    .wrap {
      max-width: 1280px;
      margin: 0 auto;
      display: flex;
      flex-direction: column;
      gap: 18px;
    }
    .hero, .panel {
      background: rgba(15, 27, 45, 0.96);
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 18px 20px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.25);
    }
    .hero h1, .panel h2 {
      margin: 0;
    }
    .hero p, .muted {
      color: var(--muted);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(0, 1fr));
      gap: 12px;
    }
    .stat {
      background: var(--panel-2);
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }
    .stat .label {
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: .05em;
      color: var(--muted);
    }
    .stat .value {
      margin-top: 8px;
      font-size: 18px;
      font-weight: 700;
      word-break: break-word;
    }
    .main {
      display: grid;
      grid-template-columns: 1.2fr .8fr;
      gap: 18px;
    }
    .section {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .form-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }
    label {
      display: flex;
      flex-direction: column;
      gap: 6px;
      font-size: 13px;
      color: var(--muted);
    }
    input, textarea {
      width: 100%;
      padding: 11px 12px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: #08111e;
      color: var(--text);
      font: inherit;
    }
    textarea {
      min-height: 180px;
      resize: vertical;
      font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 12px;
      line-height: 1.55;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }
    button {
      padding: 10px 14px;
      border-radius: 12px;
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      cursor: pointer;
      font-weight: 600;
    }
    button.primary { background: var(--blue); border-color: var(--blue); }
    button.success { background: #12361f; border-color: #1d5f34; }
    .notice, pre {
      margin: 0;
      background: #08111e;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 14px;
    }
    pre {
      white-space: pre-wrap;
      word-break: break-word;
      min-height: 220px;
      font-size: 12px;
      line-height: 1.6;
      color: #d8e7ff;
      overflow: auto;
    }
    .status-ok { color: var(--green); }
    .status-bad { color: var(--red); }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      border-radius: 999px;
      padding: 7px 10px;
      background: #08111e;
      border: 1px solid var(--line);
      color: var(--muted);
      font-size: 12px;
    }
    @media (max-width: 1100px) {
      .main, .grid, .form-grid { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <section class="hero">
      <h1>NOCKO Proxy Agent Console</h1>
      <p>Local bootstrap, configuration and diagnostics console. Keep it bound to <code>127.0.0.1</code> unless you intentionally want LAN access.</p>
      <div class="actions">
        <span class="pill">Config: <strong id="config-path">-</strong></span>
        <span class="pill">State: <strong id="state-path">-</strong></span>
      </div>
    </section>

    <section class="grid">
      <div class="stat"><div class="label">Last Success</div><div id="last-success" class="value">Never</div></div>
      <div class="stat"><div class="label">Last Error</div><div id="last-error" class="value">None</div></div>
      <div class="stat"><div class="label">Last Asset Count</div><div id="last-asset-count" class="value">0</div></div>
      <div class="stat"><div class="label">Collector Summary</div><div id="collector-summary" class="value">-</div></div>
    </section>

    <section class="main">
      <div class="section">
        <div class="panel">
          <h2>Agent Configuration</h2>
          <p class="muted">Use this form for local bootstrap and target management.</p>
          <div class="form-grid">
            <label>Portal URL<input id="portal_url" /></label>
            <label>Agent ID<input id="agent_id" /></label>
            <label>Agent Token<input id="agent_token" /></label>
            <label>Agent Name<input id="agent_name" /></label>
            <label>Site Name<input id="site_name" /></label>
            <label>Hostname<input id="hostname" /></label>
            <label>IP Address<input id="ip_address" /></label>
            <label>Version<input id="version" /></label>
            <label>Interval Seconds<input id="interval_seconds" type="number" /></label>
            <label>Collectors Enabled<input id="collectors_enabled" placeholder="snmp,redfish,lldp" /></label>
            <label>Request Timeout Seconds<input id="request_timeout_seconds" type="number" /></label>
          </div>
        </div>

        <div class="panel">
          <h2>SNMP Targets</h2>
          <p class="muted">JSON array of SNMP discovery targets. Each entry can set <code>template_key</code> like <code>avaya_1608</code>, <code>dell_idrac</code>, <code>switch_generic</code>.</p>
          <textarea id="snmp_targets"></textarea>
        </div>

        <div class="panel">
          <h2>Redfish Targets</h2>
          <p class="muted">JSON array of Redfish endpoints. For newer BMCs or iDRAC versions, use <code>template_key: dell_idrac_redfish</code>.</p>
          <textarea id="redfish_targets"></textarea>
        </div>

        <div class="panel">
          <div class="actions">
            <button class="primary" onclick="saveConfig()">Save Config</button>
            <button onclick="previewPayload()">Preview Payload</button>
            <button class="success" onclick="runSync()">Run Sync Now</button>
            <button onclick="refreshStatus()">Refresh Status</button>
          </div>
        </div>
      </div>

      <div class="section">
        <div class="panel">
          <h2>Diagnostics</h2>
          <p class="muted">Last sync result, payload preview, and runtime errors appear here.</p>
          <pre id="output">Loading…</pre>
        </div>
      </div>
    </section>
  </div>

  <script>
    function byId(id) { return document.getElementById(id); }

    function formatJson(value) {
      return JSON.stringify(value, null, 2);
    }

    function collectConfig() {
      return {
        portal_url: byId('portal_url').value.trim(),
        agent_id: byId('agent_id').value.trim(),
        agent_token: byId('agent_token').value.trim(),
        agent_name: byId('agent_name').value.trim(),
        site_name: byId('site_name').value.trim(),
        hostname: byId('hostname').value.trim(),
        ip_address: byId('ip_address').value.trim(),
        version: byId('version').value.trim(),
        interval_seconds: Number(byId('interval_seconds').value || 300),
        request_timeout_seconds: Number(byId('request_timeout_seconds').value || 30),
        collectors_enabled: byId('collectors_enabled').value.split(',').map(v => v.trim()).filter(Boolean),
        collectors: {
          snmp_targets: JSON.parse(byId('snmp_targets').value || '[]'),
          redfish_targets: JSON.parse(byId('redfish_targets').value || '[]'),
        }
      };
    }

    function setOutput(value) {
      byId('output').textContent = typeof value === 'string' ? value : formatJson(value);
    }

    async function refreshStatus() {
      const res = await fetch('/api/status');
      const data = await res.json();
      byId('config-path').textContent = data.config_path;
      byId('state-path').textContent = data.state_path;
      byId('last-success').textContent = data.state.last_success_at || 'Never';
      byId('last-error').textContent = data.state.last_error || 'None';
      byId('last-asset-count').textContent = String(data.state.last_asset_count || 0);
      byId('collector-summary').textContent = `${data.snmp_target_count} SNMP / ${data.redfish_target_count} Redfish`;
      if (data.state.last_result) {
        setOutput(data.state.last_result);
      }
    }

    async function loadConfig() {
      const res = await fetch('/api/config');
      const data = await res.json();
      byId('portal_url').value = data.portal_url || '';
      byId('agent_id').value = data.agent_id || '';
      byId('agent_token').value = data.agent_token || '';
      byId('agent_name').value = data.agent_name || '';
      byId('site_name').value = data.site_name || '';
      byId('hostname').value = data.hostname || '';
      byId('ip_address').value = data.ip_address || '';
      byId('version').value = data.version || '0.1.0';
      byId('interval_seconds').value = data.interval_seconds || 300;
      byId('request_timeout_seconds').value = data.request_timeout_seconds || 30;
      byId('collectors_enabled').value = (data.collectors_enabled || []).join(',');
      byId('snmp_targets').value = formatJson((data.collectors || {}).snmp_targets || []);
      byId('redfish_targets').value = formatJson((data.collectors || {}).redfish_targets || []);
    }

    async function saveConfig() {
      try {
        const config = collectConfig();
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        const data = await res.json();
        setOutput(data);
        await refreshStatus();
      } catch (err) {
        setOutput(String(err));
      }
    }

    async function previewPayload() {
      try {
        const config = collectConfig();
        const res = await fetch('/api/build-payload', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        const data = await res.json();
        setOutput(data);
      } catch (err) {
        setOutput(String(err));
      }
    }

    async function runSync() {
      try {
        const config = collectConfig();
        const res = await fetch('/api/run-once', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(config),
        });
        const data = await res.json();
        setOutput(data);
        await refreshStatus();
      } catch (err) {
        setOutput(String(err));
      }
    }

    async function init() {
      try {
        await loadConfig();
        await refreshStatus();
      } catch (err) {
        setOutput(String(err));
      }
    }

    init();
  </script>
</body>
</html>
"""


def _default_config() -> dict[str, Any]:
    return {
        "portal_url": "https://portal.example.com",
        "agent_id": "",
        "agent_token": "",
        "agent_name": "Proxy Agent",
        "site_name": "",
        "hostname": default_hostname(),
        "ip_address": detect_primary_ip(),
        "version": "0.1.0",
        "interval_seconds": 300,
        "request_timeout_seconds": 30,
        "collectors_enabled": ["snmp", "redfish"],
        "mqtt_enabled": True,
        "mqtt_host": "",
        "mqtt_port": 443,
        "mqtt_transport": "websockets",
        "mqtt_path": "/mqtt",
        "mqtt_tls": True,
        "mqtt_tls_verify": True,
        "mqtt_tls_allow_insecure_fallback": False,
        "mqtt_heartbeat_interval_seconds": 30,
        "collectors": {
            "snmp_targets": [],
            "redfish_targets": [],
        },
    }


def _load_or_default_config(config_path: Path) -> dict[str, Any]:
    try:
        return load_config(config_path)
    except SystemExit:
        return _default_config()


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, body: str) -> None:
    encoded = body.encode("utf-8")
    handler.send_response(HTTPStatus.OK)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    content_length = int(handler.headers.get("Content-Length", "0") or "0")
    raw = handler.rfile.read(content_length) if content_length > 0 else b"{}"
    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON body: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object.")
    return payload


def _normalize_config(payload: dict[str, Any]) -> dict[str, Any]:
    config = _default_config()
    config.update(payload)
    config["portal_url"] = normalize_server_url(str(config.get("portal_url", "") or ""))
    config["collectors_enabled"] = [
        str(item).strip()
        for item in config.get("collectors_enabled", [])
        if str(item).strip()
    ]
    collectors = config.get("collectors", {})
    if not isinstance(collectors, dict):
        collectors = {}
    config["collectors"] = {
        "snmp_targets": collectors.get("snmp_targets", []) if isinstance(collectors.get("snmp_targets", []), list) else [],
        "redfish_targets": collectors.get("redfish_targets", []) if isinstance(collectors.get("redfish_targets", []), list) else [],
    }
    return config


def _build_status_payload(config_path: Path) -> dict[str, Any]:
    config = _load_or_default_config(config_path)
    state = load_state(DEFAULT_STATE_PATH)
    collectors = config.get("collectors", {})
    return {
        "config_path": str(config_path),
        "state_path": str(DEFAULT_STATE_PATH),
        "state": state,
        "portal_url": config.get("portal_url", ""),
        "agent_name": config.get("agent_name", ""),
        "collectors_enabled": config.get("collectors_enabled", []),
        "snmp_target_count": len(collectors.get("snmp_targets", [])),
        "redfish_target_count": len(collectors.get("redfish_targets", [])),
    }


def _run_once_with_config(config: dict[str, Any]) -> dict[str, Any]:
    record_run_start()
    payload = build_payload(config)
    asset_count = len(payload.get("assets", []))
    try:
        result = post_ingest(config, payload)
    except Exception as exc:
        record_run_failure(str(exc), asset_count=asset_count)
        raise
    record_run_success(result=result, asset_count=asset_count)
    return {
        "payload_asset_count": asset_count,
        "result": result,
    }


def _make_handler(config_path: Path):
    class ConsoleHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                _html_response(self, HTML_PAGE)
                return
            if parsed.path == "/api/status":
                _json_response(self, HTTPStatus.OK, _build_status_payload(config_path))
                return
            if parsed.path == "/api/config":
                _json_response(self, HTTPStatus.OK, _load_or_default_config(config_path))
                return
            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            try:
                body = _read_json_body(self)
                if parsed.path == "/api/config":
                    existing = _load_or_default_config(config_path)
                    merged = dict(existing)
                    merged.update(body)
                    config = _normalize_config(merged)
                    save_config(config_path, config)
                    _json_response(self, HTTPStatus.OK, {"ok": True, "saved_to": str(config_path)})
                    return
                if parsed.path == "/api/build-payload":
                    config = _normalize_config(body)
                    _json_response(self, HTTPStatus.OK, build_payload(config))
                    return
                if parsed.path == "/api/run-once":
                    config = _normalize_config(body)
                    _json_response(self, HTTPStatus.OK, _run_once_with_config(config))
                    return
            except Exception as exc:
                _json_response(self, HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                return

            _json_response(self, HTTPStatus.NOT_FOUND, {"error": "Not found"})

    return ConsoleHandler


def serve_console(
    config_path: Path = DEFAULT_CONFIG_PATH,
    host: str = "127.0.0.1",
    port: int = 8771,
) -> None:
    server = ThreadingHTTPServer((host, port), _make_handler(config_path))
    print(f"NOCKO Proxy Agent console listening on http://{host}:{port}")
    try:
        server.serve_forever()
    finally:
        server.server_close()
