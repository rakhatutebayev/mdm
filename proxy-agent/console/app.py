"""
Local Web Console for NOCKO Proxy Agent.
FastAPI + Jinja2. Accessible only on local network (no internet exposure).

Routes:
  GET  /               → dashboard
  GET  /devices        → device list
  GET  /config         → view config
  POST /config         → update LOCAL ONLY fields
  POST /profiles/upload → upload Zabbix template (XML / JSON / YAML)
  GET  /logs           → tail agent log

Based on proxy_agent_tz.md Section 2.8 (Local Admin UI / Remote Portal).
"""
from __future__ import annotations

import json
import os
import traceback
from pathlib import Path
from typing import Optional

import aiofiles
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from core.config import config
from core.database import (
    Device, DeviceProfile, AuditLog, ProfileImportLog,
    get_session, kv_get
)
from core.logger import log
from core import queue as q
from core.zabbix_import import parse_zabbix_template_bytes
from sqlmodel import select

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_LOG_FILE = Path(kv_get("log_file", "/var/log/nocko-agent/agent.log"))

app = FastAPI(title="NOCKO Agent — Local Console", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


def _ctx(request: Request, **kwargs) -> dict:
    """Base template context."""
    return {
        "request": request,
        "agent_id": kv_get("agent_id", "—"),
        "tenant_id": kv_get("tenant_id", "—"),
        "broker_url": kv_get("broker_url", "—"),
        "registered": kv_get("registered", "false") == "true",
        "queue_size": q.queue_size("pending"),
        **kwargs,
    }


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    with get_session() as s:
        total_devices = len(s.exec(select(Device)).all())
        active_devices = len(s.exec(select(Device).where(Device.status == "active")).all())
        profiles = len(s.exec(select(DeviceProfile)).all())

    return templates.TemplateResponse("dashboard.html", _ctx(
        request,
        total_devices=total_devices,
        active_devices=active_devices,
        profiles=profiles,
    ))


# ──────────────────────────────────────────────────────────────────────────────
# Devices
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/devices", response_class=HTMLResponse)
async def devices(request: Request):
    with get_session() as s:
        device_list = s.exec(select(Device)).all()
    return templates.TemplateResponse("devices.html", _ctx(request, devices=device_list))


# ──────────────────────────────────────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/config", response_class=HTMLResponse)
async def config_view(request: Request):
    local = config.local.__dict__
    server_keys = {
        "heartbeat_interval": kv_get("heartbeat_interval"),
        "metrics_fast_interval": kv_get("metrics_fast_interval"),
        "metrics_slow_interval": kv_get("metrics_slow_interval"),
    }
    return templates.TemplateResponse("config.html", _ctx(
        request, local_config=local, server_config=server_keys
    ))


@app.post("/config")
async def config_update(
    request: Request,
    listen_port: int = Form(...),
    log_level: str = Form(...),
):
    """Update LOCAL ONLY config fields. Writes to config.json."""
    config.local.listen_port = listen_port
    config.local.log_level = log_level

    cfg_path = Path(__file__).parent.parent / "config.json"
    raw = {}
    if cfg_path.exists():
        raw = json.loads(cfg_path.read_text())
    raw.update({"listen_port": listen_port, "log_level": log_level})
    cfg_path.write_text(json.dumps(raw, indent=2))

    _audit("config_update", f"listen_port={listen_port}, log_level={log_level}")
    log.info(f"Local config updated: port={listen_port} log_level={log_level}")
    return RedirectResponse("/config", status_code=303)


# ──────────────────────────────────────────────────────────────────────────────
# Profile Upload
# ──────────────────────────────────────────────────────────────────────────────
@app.post("/profiles/upload")
async def profile_upload(request: Request, file: UploadFile = File(...)):
    """
    Upload a Zabbix XML template and convert to DeviceProfile.
    Conversion extracts output_mapping from items/OIDs.
    """
    filename = file.filename or "unknown.xml"
    content = await file.read()

    try:
        profile_id, profile_name, output_mapping, warnings = _convert_zabbix_xml(content)

        with get_session() as s:
            existing = s.get(DeviceProfile, profile_id)
            if existing:
                existing.output_mapping = json.dumps(output_mapping)
                existing.profile_name = profile_name
            else:
                s.add(DeviceProfile(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    output_mapping=json.dumps(output_mapping),
                ))
            s.add(ProfileImportLog(
                filename=filename,
                profile_id=profile_id,
                status="ok" if not warnings else "partial",
                warnings=json.dumps(warnings),
            ))
            s.commit()

        _audit("profile_upload", f"profile_id={profile_id}, file={filename}")
        log.info(f"Profile {profile_id} imported from {filename} ({len(warnings)} warnings)")
        return RedirectResponse("/", status_code=303)

    except Exception as e:
        log.error(f"Profile import failed: {e}\n{traceback.format_exc()}")
        with get_session() as s:
            s.add(ProfileImportLog(filename=filename, status="error", warnings=json.dumps([str(e)])))
            s.commit()
        return HTMLResponse(f"<h1>Import failed</h1><pre>{e}</pre>", status_code=400)


# ──────────────────────────────────────────────────────────────────────────────
# Logs
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/logs", response_class=HTMLResponse)
async def logs_view(request: Request, lines: int = 200):
    log_lines: list[str] = []
    try:
        if _LOG_FILE.exists():
            async with aiofiles.open(_LOG_FILE, "r", encoding="utf-8") as f:
                all_lines = await f.readlines()
                log_lines = all_lines[-lines:]
    except Exception as e:
        log_lines = [f"Error reading log: {e}"]

    return templates.TemplateResponse("logs.html", _ctx(request, log_lines=log_lines))


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────
def _audit(action: str, details: str) -> None:
    with get_session() as s:
        s.add(AuditLog(action=action, details=json.dumps({"info": details})))
        s.commit()
