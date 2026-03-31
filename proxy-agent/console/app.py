"""
Local Web Console for NOCKO Proxy Agent.
FastAPI + Jinja2. Accessible only on local network (no internet exposure).

Routes:
  GET  /               → dashboard
  GET  /devices        → device list + add form
  POST /devices/add    → create device (local DB)
  POST /devices/remove → delete device
  GET  /devices/{device_id}/latest.json → последние данные устройства (JSON, секреты замаскированы)
  GET  /devices/{device_id}/snmp-debug.json → пошаговая диагностика SNMP (MIB-II + probe OID)
  GET  /debug/json, /json-debug, /debug → JSON debug (ссылки latest + snmp-debug по устройствам)
  GET  /api/v1/console-meta.json → маркер консоли агента + список путей
  GET  /config         → view config
  POST /config         → update LOCAL ONLY fields
  POST /profiles/upload → upload Zabbix template (XML / JSON / YAML)
  POST /profiles/{id}/delete → delete profile if no devices use it
  GET  /logs           → tail agent log
  GET  /api/v1/diagnostics.json → самодиагностика (JSON; у каждого device — debug_urls → latest/snmp-debug)

Based on proxy_agent_tz.md Section 2.8 (Local Admin UI / Remote Portal).
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import time
import traceback
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote, urlencode

import aiofiles
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.exception_handlers import (
    http_exception_handler,
    request_validation_exception_handler,
)
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.config import config
from core.database import (
    Device,
    DeviceProfile,
    AuditLog,
    ProfileImportLog,
    InventoryCache,
    LLDCache,
    MetricRollup,
    QueueItem,
    get_session,
    kv_delete,
    kv_get,
    kv_set,
)
from core.logger import log
from core import queue as q
from core.zabbix_import import parse_zabbix_template_bytes
from core.profile_readiness import build_profile_row, pick_probe_oid
from core.mqtt_client import mqtt_client
from core import poll_diag
from core.debug_urls import device_debug_urls, device_id_path_ok
from core.diagnostics_report import build_diagnostics_report
from core.receipt_status import receipt_for_snap
from collectors.snmp_poller import snmp_debug_report, snmp_probe_oid
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

_VERIFY_KV_PREFIX = "profile_verify:"


def _verify_kv_key(profile_id: str) -> str:
    return f"{_VERIFY_KV_PREFIX}{profile_id}"


def _load_verify_blob(profile_id: str) -> dict[str, Any] | None:
    raw = kv_get(_verify_kv_key(profile_id), "")
    if not raw.strip():
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _save_verify_blob(profile_id: str, ok: bool, message: str) -> None:
    kv_set(
        _verify_kv_key(profile_id),
        json.dumps(
            {"at": int(time.time()), "ok": ok, "message": message[:4000]},
            ensure_ascii=False,
        ),
    )


def _clear_verify_blob(profile_id: str) -> None:
    kv_delete(_verify_kv_key(profile_id))


def _mask_secret(val: str) -> str:
    return "***" if (val or "").strip() else ""


def _device_public_dict(dev: Device) -> dict[str, Any]:
    """Device row for JSON export — без реальных SNMP-секретов."""
    return {
        "ip": dev.ip,
        "device_id": dev.device_id,
        "profile_id": dev.profile_id,
        "snmp_version": dev.snmp_version,
        "snmp_community": _mask_secret(dev.snmp_community),
        "snmp_v3_user": dev.snmp_v3_user,
        "snmp_v3_auth_key": _mask_secret(dev.snmp_v3_auth_key),
        "snmp_v3_priv_key": _mask_secret(dev.snmp_v3_priv_key),
        "poll_interval_fast": dev.poll_interval_fast,
        "poll_interval_slow": dev.poll_interval_slow,
        "poll_interval_inventory": dev.poll_interval_inventory,
        "last_seen": dev.last_seen,
        "status": dev.status,
    }


def _json_safe(o: Any) -> Any:
    """Рекурсивно приводит значения к JSON-совместимым типам."""
    if o is None or isinstance(o, (bool, int, float, str)):
        return o
    if isinstance(o, dict):
        return {str(k): _json_safe(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [_json_safe(x) for x in o]
    return str(o)


def _purge_audit_rows(s, *needles: str) -> None:
    """Best-effort local trace cleanup for delete/purge flows."""
    terms = [n for n in needles if n]
    if not terms:
        return
    for row in s.exec(select(AuditLog)).all():
        details = row.details or ""
        if any(term in details for term in terms):
            s.delete(row)


def _purge_device_local_state(s, device_id: str) -> None:
    """Delete local DB traces for one device."""
    cache = s.get(InventoryCache, device_id)
    if cache:
        s.delete(cache)
    for lc in s.exec(select(LLDCache).where(LLDCache.device_id == device_id)).all():
        s.delete(lc)
    for mr in s.exec(select(MetricRollup).where(MetricRollup.device_id == device_id)).all():
        s.delete(mr)
    for qi in s.exec(select(QueueItem).where(QueueItem.device_id == device_id)).all():
        s.delete(qi)
    _purge_audit_rows(s, device_id)


def _purge_profile_local_state(s, profile_id: str) -> None:
    """Delete local DB traces for one profile."""
    for log_row in s.exec(
        select(ProfileImportLog).where(ProfileImportLog.profile_id == profile_id)
    ).all():
        s.delete(log_row)
    _purge_audit_rows(s, profile_id)


def _safe_profile_path_id(profile_id: str) -> bool:
    return bool(re.match(r"^[a-zA-Z0-9_.-]+$", profile_id or ""))


def _load_profile_import_meta(profile: DeviceProfile) -> dict[str, Any]:
    """JSON saved at Zabbix import: description + agent_playbook + stats."""
    raw = getattr(profile, "import_meta_json", None) or "{}"
    try:
        m = json.loads(raw)
        return m if isinstance(m, dict) else {}
    except Exception:
        return {}


def _profile_probe_oid(profile_id: str) -> str | None:
    """Return first scalar OID suitable for immediate SNMP verify."""
    with get_session() as s:
        profile = s.exec(
            select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
        ).first()
    if not profile:
        return None
    try:
        mapping = json.loads(profile.output_mapping or "[]")
        if not isinstance(mapping, list):
            mapping = []
    except Exception:
        mapping = []
    return pick_probe_oid(mapping)

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_LOG_FILE = Path(kv_get("log_file", "/var/log/nocko-agent/agent.log"))

app = FastAPI(title="NOCKO Agent — Local Console", docs_url=None, redoc_url=None)
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


@app.exception_handler(Exception)
async def _console_unhandled_exception(request: Request, exc: Exception):
    """Log full traceback for 500s; keep FastAPI/Starlette HTTP and validation responses."""
    if isinstance(exc, StarletteHTTPException):
        return await http_exception_handler(request, exc)
    if isinstance(exc, RequestValidationError):
        return await request_validation_exception_handler(request, exc)
    log.exception("Local console error %s %s", request.method, request.url.path)
    accept = (request.headers.get("accept") or "").lower()
    if "application/json" in accept and request.url.path.startswith("/api/"):
        return JSONResponse(
            {"detail": "internal_error", "path": str(request.url.path)},
            status_code=500,
        )
    return HTMLResponse(
        "<h1>Internal error</h1><p>See agent log (e.g. <code>/var/log/nocko-agent/agent.log</code>).</p>",
        status_code=500,
    )


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


def _json_device_404(did: str, reason: str) -> JSONResponse:
    """Явный JSON вместо голого {\"detail\":\"Not Found\"} для *.json эндпоинтов."""
    return JSONResponse(
        status_code=404,
        content={
            "detail": reason,
            "device_id": did,
            "hint": "Откройте /devices и скопируйте точный Device UID (латиница, цифры, . _ -). "
            "Если этот ответ с портала MDM — откройте URL консоли агента (обычно :8443), не сайт портала.",
        },
    )


# ──────────────────────────────────────────────────────────────────────────────
# Обнаружение консоли (без HTML): проверка, что вы на агенте, а не на портале
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/api/v1/console-meta.json")
async def console_meta_json():
    """Минимальный маркер «это локальная консоль nocko-agent» + канонические пути JSON debug."""
    return JSONResponse(
        {
            "schema": "nocko_console_meta/1",
            "service": "nocko-agent-console",
            "paths": {
                "json_debug_html": ["/debug/json", "/json-debug"],
                "json_debug_short_redirect": "/debug",
                "diagnostics_json": "/api/v1/diagnostics.json",
                "devices_html": "/devices",
            },
        }
    )


@app.get("/debug", response_class=HTMLResponse)
async def json_debug_short_redirect():
    """Короткий редирект: /debug → /debug/json (меньше опечаток в URL)."""
    return RedirectResponse(url="/debug/json", status_code=307)


@app.get("/json-debug", response_class=HTMLResponse)
@app.get("/debug/json", response_class=HTMLResponse)
async def json_debug_hub(request: Request):
    """Всегда доступная страница со ссылками на JSON-отладку (не только из таблицы Devices)."""
    with get_session() as s:
        devs = list(s.exec(select(Device).order_by(Device.device_id)).all())
    rows: list[dict[str, Any]] = []
    for d in devs:
        u = device_debug_urls(d.device_id)
        rows.append(
            {
                "device_id": d.device_id,
                "ip": d.ip,
                "profile_id": d.profile_id or "",
                "latest_json": u.get("latest_json"),
                "snmp_debug_json": u.get("snmp_debug_json"),
                "path_ok": u.get("path_ok"),
            }
        )
    return templates.TemplateResponse(
        "json_debug.html",
        _ctx(request, debug_device_rows=rows, debug_device_count=len(rows)),
    )


# ──────────────────────────────────────────────────────────────────────────────
# Dashboard
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    snaps = poll_diag.get_all_devices()
    with get_session() as s:
        total_devices = len(s.exec(select(Device)).all())
        active_devices = len(s.exec(select(Device).where(Device.status == "active")).all())
        profiles = len(s.exec(select(DeviceProfile)).all())
        device_list = s.exec(select(Device)).all()

    receipt_rows: list[dict[str, Any]] = []
    for d in device_list:
        r = receipt_for_snap(snaps.get(d.device_id))
        du = device_debug_urls(d.device_id)
        receipt_rows.append(
            {
                "device_id": d.device_id,
                "ip": d.ip,
                "profile_id": d.profile_id or "",
                "dev_status": d.status,
                "latest_json_url": du.get("latest_json"),
                "snmp_debug_url": du.get("snmp_debug_json"),
                **r,
            }
        )
    receiving_n = sum(1 for x in receipt_rows if x.get("state") == "receiving")
    issue_n = sum(
        1 for x in receipt_rows if x.get("state") in ("error", "lld", "snmp")
    )

    import_flash = None
    if request.query_params.get("import_ok") == "1":
        try:
            n_items = int(request.query_params.get("items", 0))
        except ValueError:
            n_items = 0
        import_flash = {
            "profile_id": request.query_params.get("profile_id", ""),
            "items": n_items,
            "partial": request.query_params.get("partial") == "1",
        }

    return templates.TemplateResponse("dashboard.html", _ctx(
        request,
        total_devices=total_devices,
        active_devices=active_devices,
        profiles=profiles,
        import_flash=import_flash,
        receipt_rows=receipt_rows,
        receiving_n=receiving_n,
        receipt_issue_n=issue_n,
    ))


# ──────────────────────────────────────────────────────────────────────────────
# Devices
# ──────────────────────────────────────────────────────────────────────────────
def _devices_flash(request: Request) -> dict[str, str] | None:
    q = request.query_params
    bind_profile = (q.get("bind_profile") or q.get("profile_id") or "").strip()
    if q.get("import_ok") == "1":
        items = q.get("items", "0")
        partial = q.get("partial") == "1"
        text = (
            f"Профиль {bind_profile or '—'} импортирован: {items} SNMP mapping(s). "
            "Следующий шаг: укажите устройство, IP и SNMP-параметры, чтобы агент понял, куда слать GET/WALK."
        )
        if partial:
            text += " Часть строк шаблона была пропущена при импорте."
        return {"kind": "ok", "text": text}
    if q.get("added") == "1":
        text = "Устройство добавлено в локальную базу."
        if bind_profile:
            text += f" Профиль: {bind_profile}."
        if q.get("verify") == "1":
            if q.get("ok") == "1":
                text += " Пробный SNMP GET после привязки прошёл успешно."
            else:
                text += " Пробный SNMP GET после привязки не прошёл."
        elif q.get("verify") == "skip":
            text += " Пробный SNMP GET не выполнялся: в профиле нет scalar OID для проверки."
        return {"kind": "ok", "text": text}
    if q.get("removed") == "1":
        return {"kind": "ok", "text": "Устройство удалено."}
    err = (q.get("err") or "").strip()
    if err:
        messages = {
            "bad_uid": "Некорректный Device UID (латиница, цифры, . _ -).",
            "bad_ip": "Некорректный IP-адрес.",
            "profile": "Такого профиля нет — выберите из списка или оставьте пустым.",
            "duplicate": "Устройство с таким UID уже есть.",
            "missing": "Устройство не найдено.",
        }
        return {"kind": "err", "text": messages.get(err, "Ошибка сохранения.")}
    return None


@app.get("/devices", response_class=HTMLResponse)
async def devices(request: Request):
    snaps = poll_diag.get_all_devices()
    with get_session() as s:
        device_list = s.exec(select(Device)).all()
        profile_list = s.exec(
            select(DeviceProfile).order_by(DeviceProfile.profile_id)
        ).all()
    bind_profile = (request.query_params.get("bind_profile") or "").strip()
    bind_profile_row = next(
        (p for p in profile_list if p.profile_id == bind_profile),
        None,
    )
    device_rows = [
        {
            "d": d,
            "receipt": receipt_for_snap(snaps.get(d.device_id)),
        }
        for d in device_list
    ]
    return templates.TemplateResponse(
        "devices.html",
        _ctx(
            request,
            device_rows=device_rows,
            profile_list=profile_list,
            devices_flash=_devices_flash(request),
            bind_profile=bind_profile_row,
        ),
    )

@app.get("/devices/add", response_class=HTMLResponse)
async def devices_add_form(request: Request, bind: str = "", closed: bool = False, err: str = ""):
    """Popup page for adding a device. After submit, closes and reloads parent."""
    with get_session() as s:
        profile_list = s.exec(
            select(DeviceProfile).order_by(DeviceProfile.profile_id)
        ).all()
    bind_profile_row = next(
        (p for p in profile_list if p.profile_id == bind),
        None,
    ) if bind else None
    flash_err = {
        "bad_uid": "Неверный Device UID (только латиница, цифры, . _ -)",
        "bad_ip": "Неверный формат IP адреса",
        "profile": "Профиль не найден",
        "duplicate": "Устройство с таким UID уже существует",
    }.get(err, "")
    return templates.TemplateResponse(
        "device_add.html",
        _ctx(
            request,
            profile_list=profile_list,
            bind_profile=bind_profile_row,
            closed=closed,
            flash_err=flash_err,
        ),
    )


@app.post("/devices/add")
async def devices_add(
    request: Request,
    device_uid: str = Form(...),
    ip: str = Form(...),
    profile_id: str = Form(""),
    collector_type: str = Form("snmp"),
    snmp_version: str = Form("2c"),
    snmp_community: str = Form("public"),
    snmp_v3_user: str = Form(""),
    snmp_v3_auth_key: str = Form(""),
    snmp_v3_priv_key: str = Form(""),
    vmware_url: str = Form(""),
    vmware_username: str = Form(""),
    vmware_password: str = Form(""),
    ssh_user: str = Form("root"),
    ssh_password: str = Form(""),
    status: str = Form("active"),
):
    popup = request.query_params.get("popup") == "1"
    bind  = request.query_params.get("bind", "")

    """Create a polled device in local SQLite (not synced from MDM automatically)."""
    uid = (device_uid or "").strip()
    if not re.match(r"^[a-zA-Z0-9_.-]+$", uid):
        err_url = "err=bad_uid"
        if popup:
            return RedirectResponse(f"/devices/add?{err_url}&bind={bind}", status_code=303)
        return RedirectResponse(f"/devices?{err_url}", status_code=303)
    ip_s = (ip or "").strip()
    try:
        ipaddress.ip_address(ip_s)
    except ValueError:
        err_url = "err=bad_ip"
        if popup:
            return RedirectResponse(f"/devices/add?{err_url}&bind={bind}", status_code=303)
        return RedirectResponse(f"/devices?{err_url}", status_code=303)

    pid = (profile_id or "").strip() or None
    if pid:
        with get_session() as s:
            if not s.exec(
                select(DeviceProfile).where(DeviceProfile.profile_id == pid)
            ).first():
                if popup:
                    return RedirectResponse(f"/devices/add?err=profile&bind={bind}", status_code=303)
                return RedirectResponse("/devices?err=profile", status_code=303)

    ct_raw = (collector_type or "").strip()
    if ct_raw == "vmware":
        ctype = "vmware"
    elif ct_raw == "esxi_ssh":
        ctype = "esxi_ssh"
    else:
        ctype = "snmp"
    ver = "3" if (snmp_version or "").strip() == "3" else "2c"
    st = (status or "active").strip()
    if st not in ("active", "offline", "unsupported"):
        st = "active"

    # For esxi_ssh: store SSH password in snmp_community, SSH user in snmp_v3_user
    if ctype == "esxi_ssh":
        effective_community = (ssh_password or "").strip()
        effective_v3_user   = (ssh_user or "root").strip()
    else:
        effective_community = (snmp_community or "public").strip() or "public"
        effective_v3_user   = (snmp_v3_user or "").strip()

    dev = Device(
        device_id=uid,
        ip=ip_s,
        profile_id=pid,
        collector_type=ctype,
        snmp_version=ver,
        snmp_community=effective_community,
        snmp_v3_user=effective_v3_user,
        snmp_v3_auth_key=(snmp_v3_auth_key or "").strip(),
        snmp_v3_priv_key=(snmp_v3_priv_key or "").strip(),
        vmware_url=(vmware_url or "").strip(),
        vmware_username=(vmware_username or "").strip(),
        vmware_password=(vmware_password or "").strip(),
        status=st,
    )

    try:
        with get_session() as s:
            s.add(dev)
            s.commit()
            # После commit атрибуты истекают; без refresh+expunge snmp_probe_oid падает
            # с DetachedInstanceError при чтении dev.ip вне сессии.
            s.refresh(dev)
            s.expunge(dev)
    except IntegrityError:
        if popup:
            return RedirectResponse(f"/devices/add?err=duplicate&bind={bind}", status_code=303)
        return RedirectResponse("/devices?err=duplicate", status_code=303)

    _audit("device_add", f"device_id={uid} ip={ip_s} profile_id={pid or ''}")
    log.info(f"Console: added device {uid} @ {ip_s}")

    if popup:
        return RedirectResponse("/devices/add?closed=1", status_code=303)

    if not pid:
        return RedirectResponse("/devices?added=1", status_code=303)

    # VMware devices don't use SNMP — skip probe
    if ctype == "vmware":
        q = urlencode({"added": "1", "profile_id": pid, "verify": "skip"})
        return RedirectResponse(f"/devices?{q}", status_code=303)

    probe_oid = _profile_probe_oid(pid)
    if not probe_oid:
        q = urlencode({"added": "1", "profile_id": pid, "verify": "skip"})
        return RedirectResponse(f"/devices?{q}", status_code=303)

    ok, msg = await snmp_probe_oid(dev, probe_oid)
    _save_verify_blob(pid, ok, msg)
    log.info(f"Auto-verify after device bind profile={pid}: ok={ok} {msg}")
    q = urlencode(
        {
            "added": "1",
            "profile_id": pid,
            "verify": "1",
            "ok": "1" if ok else "0",
        }
    )
    return RedirectResponse(f"/devices?{q}", status_code=303)



@app.get("/devices/{device_id}/edit", response_class=HTMLResponse)
async def devices_edit_form(request: Request, device_id: str, closed: bool = False, err: str = ""):
    """Popup page for editing a device."""
    did = (device_id or "").strip()
    if not device_id_path_ok(did):
        return HTMLResponse("Invalid device ID", status_code=400)

    with get_session() as s:
        device = s.exec(select(Device).where(Device.device_id == did)).first()
        if not device:
            return HTMLResponse("Device not found", status_code=404)
        profile_list = s.exec(select(DeviceProfile).order_by(DeviceProfile.profile_id)).all()

    flash_err = {
        "bad_ip": "Неверный формат IP адреса",
        "profile": "Профиль не найден",
    }.get(err, "")

    return templates.TemplateResponse(
        "device_edit.html",
        _ctx(
            request,
            device=device,
            profile_list=profile_list,
            closed=closed,
            flash_err=flash_err,
        ),
    )


@app.post("/devices/{device_id}/edit")
async def devices_edit(
    request: Request,
    device_id: str,
    ip: str = Form(...),
    profile_id: str = Form(""),
    collector_type: str = Form("snmp"),
    snmp_version: str = Form("2c"),
    snmp_community: str = Form("public"),
    snmp_v3_user: str = Form(""),
    snmp_v3_auth_key: str = Form(""),
    snmp_v3_priv_key: str = Form(""),
    vmware_url: str = Form(""),
    vmware_username: str = Form(""),
    vmware_password: str = Form(""),
    ssh_user: str = Form("root"),
    ssh_password: str = Form(""),
    status: str = Form("active"),
):
    did = (device_id or "").strip()
    if not device_id_path_ok(did):
        return HTMLResponse("Invalid device ID", status_code=400)

    popup = request.query_params.get("popup") == "1"

    ip_s = (ip or "").strip()
    try:
        ipaddress.ip_address(ip_s)
    except ValueError:
        if popup:
            return RedirectResponse(f"/devices/{did}/edit?err=bad_ip&popup=1", status_code=303)
        return RedirectResponse(f"/devices?err=bad_ip", status_code=303)

    pid = (profile_id or "").strip() or None
    if pid:
        with get_session() as s:
            if not s.exec(select(DeviceProfile).where(DeviceProfile.profile_id == pid)).first():
                if popup:
                    return RedirectResponse(f"/devices/{did}/edit?err=profile&popup=1", status_code=303)
                return RedirectResponse("/devices?err=profile", status_code=303)

    st = (status or "active").strip()
    if st not in ("active", "offline", "unsupported"):
        st = "active"

    ct_raw = (collector_type or "").strip()
    if ct_raw == "vmware":
        ctype = "vmware"
    elif ct_raw == "esxi_ssh":
        ctype = "esxi_ssh"
    else:
        ctype = "snmp"

    # Credential routing
    if ctype == "esxi_ssh":
        effective_community = (ssh_password or "").strip()
        effective_v3_user   = (ssh_user or "root").strip()
    else:
        effective_community = (snmp_community or "public").strip() or "public"
        effective_v3_user   = (snmp_v3_user or "").strip()

    with get_session() as s:
        dev = s.exec(select(Device).where(Device.device_id == did)).first()
        if not dev:
            return RedirectResponse("/devices?err=missing", status_code=303)

        dev.ip = ip_s
        dev.profile_id = pid
        dev.collector_type = ctype
        dev.snmp_version = "3" if (snmp_version or "").strip() == "3" else "2c"
        dev.snmp_community = effective_community
        dev.snmp_v3_user = effective_v3_user
        dev.snmp_v3_auth_key = (snmp_v3_auth_key or "").strip()
        dev.snmp_v3_priv_key = (snmp_v3_priv_key or "").strip()
        dev.vmware_url = (vmware_url or "").strip()
        dev.vmware_username = (vmware_username or "").strip()
        dev.vmware_password = (vmware_password or "").strip()
        dev.status = st

        s.add(dev)
        s.commit()
        s.refresh(dev)
        s.expunge(dev)

    _audit("device_edit", f"device_id={did} ip={ip_s} profile_id={pid or ''}")
    log.info(f"Console: updated device {did} @ {ip_s}")

    if popup:
        return RedirectResponse(f"/devices/{did}/edit?closed=1&popup=1", status_code=303)

    if not pid or ctype == "vmware":
        return RedirectResponse("/devices?updated=1", status_code=303)

    # SNMP probe if profile changed or IP changed
    probe_oid = _profile_probe_oid(pid)
    if probe_oid:
        ok, msg = await snmp_probe_oid(dev, probe_oid)
        _save_verify_blob(pid, ok, msg)
        log.info(f"Auto-verify after device update profile={pid}: ok={ok} {msg}")

    return RedirectResponse("/devices?updated=1", status_code=303)


@app.post("/devices/remove")
async def devices_remove(device_id: str = Form(...)):
    did = (device_id or "").strip()
    if not did:
        return RedirectResponse("/devices?err=missing", status_code=303)
    with get_session() as s:
        row = s.exec(select(Device).where(Device.device_id == did)).first()
        if not row:
            return RedirectResponse("/devices?err=missing", status_code=303)
        _purge_device_local_state(s, did)
        s.delete(row)
        s.commit()
    poll_diag.clear_device(did)
    try:
        from collectors.snmp_poller import forget_device

        forget_device(did)
    except Exception:
        pass
    log.info(f"Console: removed device {did}")
    return RedirectResponse("/devices?removed=1", status_code=303)


@app.get("/devices/{device_id}/latest.json")
async def devices_latest_json(device_id: str):
    """Последний снимок: запись устройства, poll_diag, кэш инвентаря, статус приёма."""
    did = (device_id or "").strip()
    if not device_id_path_ok(did):
        return _json_device_404(did, "invalid_device_id_in_path")
    with get_session() as s:
        row = s.exec(select(Device).where(Device.device_id == did)).first()
        if not row:
            return _json_device_404(did, "device_not_found")
        inv = s.get(InventoryCache, did)
    snap = poll_diag.get_snapshot(did)
    inv_payload: Any = None
    inv_meta: dict[str, Any] | None = None
    if inv is not None:
        inv_meta = {
            "collected_at": inv.collected_at.isoformat() if inv.collected_at else None,
        }
        try:
            inv_payload = json.loads(inv.data_json or "{}")
        except Exception:
            inv_payload = {
                "_parse_error": True,
                "raw_preview": (inv.data_json or "")[:2000],
            }
    body = {
        "schema": "nocko_device_latest/1",
        "generated_at": time.time(),
        "device_id": did,
        "device": _device_public_dict(row),
        "receipt": receipt_for_snap(snap),
        "poll_diag": _json_safe(snap),
        "inventory_cache": inv_payload,
        "inventory_cache_meta": inv_meta,
    }
    return JSONResponse(content=body)


@app.get("/devices/{device_id}/snmp-debug.json")
async def devices_snmp_debug_json(device_id: str):
    """MIB-II GET + probe OID профиля + текстовые подсказки (один запрос к агенту)."""
    did = (device_id or "").strip()
    if not device_id_path_ok(did):
        return _json_device_404(did, "invalid_device_id_in_path")
    with get_session() as s:
        row = s.exec(select(Device).where(Device.device_id == did)).first()
        if not row:
            return _json_device_404(did, "device_not_found")
    report = await snmp_debug_report(row)
    report["generated_at"] = time.time()
    return JSONResponse(content=report)


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
        profile_id, profile_name, output_mapping, warnings, import_meta = (
            parse_zabbix_template_bytes(content, filename)
        )
        import_meta_json = json.dumps(import_meta, ensure_ascii=False)

        tech = import_meta.get("template_technology", "")
        if not output_mapping:
            _TECH_MSGS = {
                "vmware": (
                    "VMware template — нет SNMP items. "
                    "Шаблон использует Zabbix VMware API (vmware.* ключи), а не SNMP. "
                    "Агент не сможет опрашивать устройства по этому профилю через SNMP. "
                    "Профиль сохранён, но SNMP polling работать не будет."
                ),
                "ipmi": (
                    "IPMI template — нет SNMP items. "
                    "Профиль сохранён, но SNMP polling работать не будет."
                ),
                "http_agent": (
                    "HTTP Agent / Script template — нет SNMP items. "
                    "Профиль сохранён, но SNMP polling работать не будет."
                ),
            }
            default_warn = (
                "В шаблоне нет SNMP items (snmp_oid + key). "
                "Профиль сохранён, но SNMP polling работать не будет."
            )
            warnings.insert(0, f"[NON-SNMP] {_TECH_MSGS.get(tech, default_warn)}")

        with get_session() as s:
            existing = s.exec(
                select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
            ).first()
            if existing:
                existing.output_mapping = json.dumps(output_mapping)
                existing.profile_name = profile_name
                existing.import_meta_json = import_meta_json
                s.add(existing)
            else:
                s.add(DeviceProfile(
                    profile_id=profile_id,
                    profile_name=profile_name,
                    output_mapping=json.dumps(output_mapping),
                    import_meta_json=import_meta_json,
                ))
            status = "non_snmp" if (not output_mapping) else ("partial" if warnings else "ok")
            s.add(ProfileImportLog(
                filename=filename,
                profile_id=profile_id,
                status=status,
                warnings=json.dumps(warnings),
            ))
            s.commit()

        _audit("profile_upload", f"profile_id={profile_id}, file={filename}")
        pb = import_meta.get("agent_playbook") or []
        log.info(
            f"Profile {profile_id} imported from {filename} ({len(warnings)} warnings, tech={tech or 'snmp'}). "
            f"Playbook: {pb[0] if pb else '—'}"
        )
        q = urlencode(
            {
                "import_ok": "1",
                "profile_id": profile_id,
                "bind_profile": profile_id,
                "items": str(len(output_mapping)),
                "partial": "1" if warnings else "0",
            }
        )
        return RedirectResponse(f"/devices?{q}", status_code=303)

    except Exception as e:
        log.error(f"Profile import failed: {e}\n{traceback.format_exc()}")
        with get_session() as s:
            s.add(ProfileImportLog(filename=filename, status="error", warnings=json.dumps([str(e)])))
            s.commit()
        return HTMLResponse(f"<h1>Import failed</h1><pre>{e}</pre>", status_code=400)


# ──────────────────────────────────────────────────────────────────────────────
# Profiles (TZ §2.4 — list, requisites, readiness, SNMP verify)
# ──────────────────────────────────────────────────────────────────────────────
@app.get("/profiles", response_class=HTMLResponse)
async def profiles_list(request: Request):
    import_flash = None
    if request.query_params.get("import_ok") == "1":
        try:
            n_items = int(request.query_params.get("items", 0))
        except ValueError:
            n_items = 0
        import_flash = {
            "profile_id": request.query_params.get("profile_id", ""),
            "items": n_items,
            "partial": request.query_params.get("partial") == "1",
        }
    highlight = request.query_params.get("highlight", "")
    deleted_profile_id = ""
    if request.query_params.get("deleted") == "1":
        deleted_profile_id = (request.query_params.get("profile_id") or "").strip()

    rows: list[Any] = []
    with get_session() as s:
        plist = s.exec(select(DeviceProfile).order_by(DeviceProfile.profile_id)).all()
        for p in plist:
            vb = _load_verify_blob(p.profile_id)
            rows.append(build_profile_row(s, p, vb))

    return templates.TemplateResponse(
        "profiles.html",
        _ctx(
            request,
            rows=rows,
            import_flash=import_flash,
            highlight=highlight,
            deleted_profile_id=deleted_profile_id,
        ),
    )


@app.get("/profiles/{profile_id}", response_class=HTMLResponse)
async def profile_detail(request: Request, profile_id: str):
    if not _safe_profile_path_id(profile_id):
        return HTMLResponse("Invalid profile_id", status_code=400)

    verify_banner = None
    verify_ok = True
    if request.query_params.get("vf") == "1":
        verify_ok = request.query_params.get("ok") == "1"
        verify_banner = (
            "SNMP verification succeeded."
            if verify_ok
            else "SNMP verification failed — see message below."
        )
    delete_err = (request.query_params.get("delete_err") or "").strip()

    with get_session() as s:
        profile = s.exec(
            select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
        ).first()
        if not profile:
            return HTMLResponse("Profile not found", status_code=404)
        vb = _load_verify_blob(profile_id)
        row = build_profile_row(s, profile, vb)

    try:
        mapping = json.loads(profile.output_mapping or "[]")
        if not isinstance(mapping, list):
            mapping = []
    except Exception:
        mapping = []

    probe_oid = pick_probe_oid(mapping)
    preview = mapping[:40]
    devices_count = row.devices_count

    import_meta = _load_profile_import_meta(profile)

    return templates.TemplateResponse(
        "profile_detail.html",
        _ctx(
            request,
            profile=profile,
            row=row,
            probe_oid=probe_oid,
            devices_count=devices_count,
            mapping_preview=preview,
            mapping_total=len(mapping),
            mapping_preview_json=json.dumps(preview, indent=2, ensure_ascii=False),
            verify_banner=verify_banner,
            verify_ok=verify_ok,
            import_meta=import_meta,
            delete_err=delete_err,
        ),
    )


@app.post("/profiles/{profile_id}/delete")
async def profile_delete(profile_id: str):
    """Remove profile only when no Device rows reference this profile_id (FK safety)."""
    if not _safe_profile_path_id(profile_id):
        return HTMLResponse("Invalid profile_id", status_code=400)

    with get_session() as s:
        profile = s.exec(
            select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
        ).first()
        if not profile:
            return HTMLResponse("Not found", status_code=404)

        n_bound = len(
            s.exec(select(Device).where(Device.profile_id == profile_id)).all()
        )
        if n_bound > 0:
            log.warning(
                f"Profile delete blocked: {profile_id} still has {n_bound} device(s)"
            )
            return RedirectResponse(
                f"/profiles/{profile_id}?delete_err=in_use", status_code=303
            )

        _purge_profile_local_state(s, profile_id)
        s.delete(profile)
        s.commit()

    _clear_verify_blob(profile_id)
    log.info(f"Profile deleted: {profile_id}")

    return RedirectResponse(
        f"/profiles?deleted=1&profile_id={quote(profile_id, safe='')}",
        status_code=303,
    )


@app.post("/profiles/{profile_id}/meta")
async def profile_meta_update(
    request: Request,
    profile_id: str,
    profile_name: str = Form(...),
    profile_vendor: str = Form(""),
    profile_version: str = Form(""),
):
    if not _safe_profile_path_id(profile_id):
        return HTMLResponse("Invalid profile_id", status_code=400)
    with get_session() as s:
        profile = s.exec(
            select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
        ).first()
        if not profile:
            return HTMLResponse("Not found", status_code=404)
        profile.profile_name = profile_name.strip()
        profile.profile_vendor = (profile_vendor or "").strip()
        profile.profile_version = (profile_version or "").strip()
        s.add(profile)
        s.commit()
    _audit("profile_meta", f"profile_id={profile_id}")
    return RedirectResponse(f"/profiles/{profile_id}?updated=meta", status_code=303)


@app.post("/profiles/{profile_id}/verify")
async def profile_verify(profile_id: str):
    if not _safe_profile_path_id(profile_id):
        return HTMLResponse("Invalid profile_id", status_code=400)

    with get_session() as s:
        profile = s.exec(
            select(DeviceProfile).where(DeviceProfile.profile_id == profile_id)
        ).first()
        if not profile:
            return HTMLResponse("Not found", status_code=404)
        try:
            mapping = json.loads(profile.output_mapping or "[]")
            if not isinstance(mapping, list):
                mapping = []
        except Exception:
            mapping = []
        oid = pick_probe_oid(mapping)
        dev = s.exec(
            select(Device)
            .where(Device.profile_id == profile_id)
            .where(Device.status == "active")
        ).first()
        if not dev:
            dev = s.exec(
                select(Device).where(Device.profile_id == profile_id)
            ).first()
        if dev is not None:
            s.expunge(dev)

    if not oid:
        _save_verify_blob(profile_id, False, "No scalar OID in mapping (LLD-only template).")
        return RedirectResponse(f"/profiles/{profile_id}?vf=1&ok=0", status_code=303)

    if not dev:
        _save_verify_blob(
            profile_id,
            False,
            "No device assigned to this profile — add a device first.",
        )
        return RedirectResponse(f"/profiles/{profile_id}?vf=1&ok=0", status_code=303)

    ok, msg = await snmp_probe_oid(dev, oid)
    _save_verify_blob(profile_id, ok, msg)
    log.info(f"Profile {profile_id} SNMP verify: ok={ok} {msg}")
    return RedirectResponse(f"/profiles/{profile_id}?vf=1&ok={'1' if ok else '0'}", status_code=303)


def _format_tier_snap(s: dict | None) -> str:
    if not s:
        return "— (no poll yet)"
    if s.get("error"):
        return f"err:{s.get('error')}"
    parts = [
        f"tot={s.get('tier_total', 0)}",
        f"macro={s.get('macro_skipped', 0)}",
        f"snmp_fail={s.get('snmp_failed', 0)}",
    ]
    if "dedup_skipped" in s:
        parts.append(f"dedup={s.get('dedup_skipped', 0)}")
    if "range_skipped" in s:
        parts.append(f"range={s.get('range_skipped', 0)}")
    parts.append(f"pub={s.get('values_published', 0)}")
    parts.append("mqtt=ok" if s.get("mqtt_ok") else "mqtt=no")
    sk = s.get("sample_keys")
    if isinstance(sk, list) and sk:
        n = int(s.get("values_published", 0))
        tail = f" (+{n - len(sk)} more)" if n > len(sk) else ""
        parts.append("keys=" + ",".join(str(x) for x in sk) + tail)
    age = int(time.time()) - int(s.get("ts", 0))
    parts.append(f"age={age}s")
    return " ".join(parts)


@app.get("/diagnostics", response_class=HTMLResponse)
async def diagnostics_page(request: Request):
    """Proxy-side SNMP → MQTT troubleshooting (TZ local ops)."""
    tenant_s = str(config.server.tenant_id or kv_get("tenant_id", "")) or "—"
    agent_s = str(config.server.agent_id or kv_get("agent_id", "")) or "—"
    broker_s = (kv_get("broker_url", "") or config.server.broker_url or "").strip() or "—"

    snaps = poll_diag.get_all_devices()
    rows: list[dict[str, Any]] = []
    state_counts: dict[str, int] = {}
    with get_session() as s:
        devs = s.exec(select(Device)).all()
    for d in devs:
        snap = snaps.get(d.device_id, {})
        rec = receipt_for_snap(snap)
        st = str(rec.get("state") or "unknown")
        state_counts[st] = state_counts.get(st, 0) + 1
        du = device_debug_urls(d.device_id)
        rows.append(
            {
                "device_id": d.device_id,
                "ip": d.ip,
                "profile_id": d.profile_id or "",
                "receipt": rec,
                "fast": _format_tier_snap(snap.get("fast")),
                "slow": _format_tier_snap(snap.get("slow")),
                "inv": _format_tier_snap(snap.get("inventory")),
                "latest_json": du.get("latest_json"),
                "snmp_debug_json": du.get("snmp_debug_json"),
                "path_ok": du.get("path_ok"),
            }
        )

    problems_n = (
        state_counts.get("error", 0)
        + state_counts.get("lld", 0)
        + state_counts.get("snmp", 0)
    )
    diag_summary = {
        "receiving": state_counts.get("receiving", 0),
        "stale": state_counts.get("stale", 0),
        "inventory_only": state_counts.get("inventory_only", 0),
        "idle": state_counts.get("idle", 0),
        "unknown": state_counts.get("unknown", 0),
        "problems": problems_n,
        "total": len(devs),
    }

    return templates.TemplateResponse(
        "diagnostics.html",
        _ctx(
            request,
            tenant_id=tenant_s,
            agent_id=agent_s,
            broker_url=broker_s,
            mqtt_connected=mqtt_client.connected,
            queue_pending=q.queue_size("pending"),
            devices=rows,
            diag_summary=diag_summary,
        ),
    )


@app.get("/api/v1/diagnostics.json")
async def diagnostics_json():
    """Снимок MQTT + SNMP-приём по устройствам для мониторинга и скриптов (локальная сеть)."""
    return JSONResponse(build_diagnostics_report())


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
