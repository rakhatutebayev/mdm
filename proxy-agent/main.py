"""
NOCKO Proxy Agent — Main Entry Point.

Starts all async components:
  1. SQLite DB init
  2. Bootstrap (register if needed, fetch config)
  3. MQTT client connect
  4. Heartbeat loop
  5. SNMP poller loop
  6. Trap receiver (UDP :162)
  7. Local Web Console (FastAPI/Uvicorn)
  8. Offline queue flush loop

Usage:
  python main.py [--dev]

  --dev  Skip bootstrap + MQTT (run console-only for local testing)
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import time

import uvicorn

from core.config import load_config, config
from core.database import init_db, kv_get
from core.logger import setup_logger, log
from core.mqtt_client import mqtt_client
from core import queue as q


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="NOCKO Proxy Agent")
    p.add_argument("--dev", action="store_true", help="Dev mode: skip MQTT and bootstrap")
    p.add_argument("--config", default=None, help="Path to config.json")
    return p.parse_args()


async def _heartbeat_loop() -> None:
    """Send agent_presence heartbeat via MQTT every heartbeat_interval seconds."""
    while True:
        try:
            pending = q.queue_size("pending")
            mqtt_client.publish_heartbeat(queue_size=pending)
        except Exception as e:
            log.debug(f"Heartbeat error: {e}")
        await asyncio.sleep(config.server.heartbeat_interval)


async def _queue_flush_loop() -> None:
    """Periodically flush offline queue when MQTT is connected."""
    while True:
        await asyncio.sleep(30)
        try:
            mqtt_client.flush_queue()
            q.prune_sent(older_than_hours=48)
        except Exception as e:
            log.debug(f"Queue flush error: {e}")


async def _command_handler(payload: dict) -> None:
    """Handle incoming MQTT command from portal."""
    from core.database import Command, CommandResult, get_session
    from sqlmodel import select
    from sqlalchemy.exc import IntegrityError

    import json

    command_id = payload.get("command_id", "")
    command_type = payload.get("command_type", "")
    log.info(f"Executing command {command_type} [{command_id}]")

    # Persist to commands table (idempotent if portal retries same command_id)
    with get_session() as s:
        cmd = Command(
            command_id=command_id,
            command_type=command_type,
            issued_at=payload.get("issued_at", int(time.time())),
            issued_by=payload.get("issued_by", "portal"),
            payload=json.dumps(payload.get("payload", {})),
            status="running",
        )
        s.add(cmd)
        try:
            s.commit()
        except IntegrityError:
            s.rollback()
            existing = s.exec(select(Command).where(Command.command_id == command_id)).first()
            if existing:
                existing.status = "running"
                s.add(existing)
                s.commit()
            else:
                raise

    result = ""
    error = None
    try:
        if command_type == "reload_config":
            from core.bootstrap import fetch_config, apply_kv_identity_to_server_config
            fetch_config()
            apply_kv_identity_to_server_config()
            result = "Config reloaded"

        elif command_type == "refresh_profiles":
            from core.bootstrap import fetch_config, apply_kv_identity_to_server_config
            fetch_config()
            apply_kv_identity_to_server_config()
            result = "Server config re-fetched (local Zabbix profiles unchanged)"

        elif command_type == "ping":
            result = "pong"

        elif command_type == "request_diag_bundle":
            result = f"agent_id={kv_get('agent_id')} queue_pending={q.queue_size('pending')}"

        elif command_type == "pause_polling":
            from collectors.snmp_poller import pause_polling
            pause_polling()
            result = "Polling paused"

        elif command_type == "resume_polling":
            from collectors.snmp_poller import resume_polling
            resume_polling()
            result = "Polling resumed"

        elif command_type == "start_inventory_now":
            from collectors.snmp_poller import request_immediate_inventory
            request_immediate_inventory()
            result = "Inventory poll scheduled for next poller tick"

        elif command_type == "start_metrics_now":
            from collectors.snmp_poller import request_immediate_metrics
            request_immediate_metrics(include_fast=True, include_slow=True)
            result = "Fast+slow metrics poll scheduled for next poller tick"

        elif command_type == "restart_agent_service":
            result = (
                "Not executed from agent process: run on host "
                "`sudo systemctl restart nocko-agent` (or equivalent)"
            )

        elif command_type == "update_agent":
            log.warning("OTA update requested — not implemented in MVP")
            result = "OTA update: not implemented in MVP"

        else:
            log.warning(f"Unknown command type: {command_type}")
            result = f"Unknown command: {command_type}"

    except Exception as e:
        error = str(e)
        log.error(f"Command {command_id} failed: {e}")

    # Persist result and publish back
    with get_session() as s:
        cmd_row = s.exec(select(Command).where(Command.command_id == command_id)).first()
        if cmd_row:
            cmd_row.status = "failed" if error else "done"
        else:
            log.warning(f"Command row missing for command_id={command_id}, cannot set status")
        s.add(CommandResult(
            command_id=command_id,
            status="failed" if error else "done",
            result=result,
            error_message=error,
        ))
        s.commit()

    result_payload = {
        "command_id": command_id,
        "status": "failed" if error else "done",
        "result": result,
        "error_message": error,
        "finished_at": int(time.time()),
    }
    mqtt_client.publish("command_results", result_payload)


async def main(dev_mode: bool = False, config_path: str | None = None) -> None:
    # 1. Load local config
    load_config(config_path)
    setup_logger("nocko-agent", config.local.log_level)
    log.info(f"NOCKO Proxy Agent starting (dev={dev_mode})")

    # 2. Init SQLite
    from pathlib import Path
    Path(config.local.db_path).parent.mkdir(parents=True, exist_ok=True)
    init_db(config.local.db_path)

    if not dev_mode:
        # 3. Bootstrap: register if needed
        from core.bootstrap import register, fetch_config
        registered = kv_get("registered", "false") == "true"
        if not registered:
            token = config.local.enrollment_token
            if not token:
                log.error("enrollment_token not set in config.json. Cannot register.")
                sys.exit(1)
            register(token)

        # 4. Fetch server config
        from core.bootstrap import apply_kv_identity_to_server_config
        try:
            fetch_config()
        except Exception as e:
            log.warning(f"Could not fetch server config: {e}. Using cached values.")
        # Envelopes need tenant_id/agent_id even if GET /config failed (use KV from register)
        apply_kv_identity_to_server_config()

        # 5. Setup + connect MQTT
        mqtt_client.setup()
        mqtt_client.on_command(lambda p: asyncio.create_task(_command_handler(p)))
        mqtt_client.on_config_signal(lambda: asyncio.create_task(_on_config_signal()))
        mqtt_client.connect()

    # 6. Assemble async tasks
    from collectors.snmp_poller import run_poller
    from collectors.trap_receiver import run_trap_receiver
    from console.app import app as console_app

    tasks = [
        asyncio.create_task(run_poller()),
        asyncio.create_task(run_trap_receiver(port=162)),
        asyncio.create_task(_queue_flush_loop()),
    ]

    if not dev_mode:
        tasks.append(asyncio.create_task(_heartbeat_loop()))

    # 7. Start Uvicorn (Local Web Console) — HTTPS when ui.crt/ui.key exist (see install.sh)
    uv_kwargs: dict = {
        "app": console_app,
        "host": config.local.listen_host,
        "port": config.local.listen_port,
        "log_level": "warning",
    }
    use_tls = getattr(config.local, "console_tls", True)
    cert_path = config.console_cert_path
    key_path = config.console_key_path
    if use_tls and cert_path.is_file() and key_path.is_file():
        uv_kwargs["ssl_certfile"] = str(cert_path)
        uv_kwargs["ssl_keyfile"] = str(key_path)
        scheme = "https"
    else:
        if use_tls and not cert_path.is_file():
            log.warning(
                f"console_tls enabled but {cert_path} missing — falling back to HTTP "
                "(run install.sh or set console_tls false)"
            )
        scheme = "http"

    uv_config = uvicorn.Config(**uv_kwargs)
    server = uvicorn.Server(uv_config)
    tasks.append(asyncio.create_task(server.serve()))

    log.info(f"Local console: {scheme}://{config.local.listen_host}:{config.local.listen_port}")

    # Run until cancelled / crash
    try:
        await asyncio.gather(*tasks)
    except asyncio.CancelledError:
        log.info("Agent shutdown")


async def _on_config_signal() -> None:
    """Re-fetch server config when portal signals a change."""
    from core.bootstrap import fetch_config, apply_kv_identity_to_server_config
    log.info("Config change signal received — re-fetching from MDM")
    try:
        fetch_config()
        apply_kv_identity_to_server_config()
    except Exception as e:
        log.error(f"Config re-fetch failed: {e}")


if __name__ == "__main__":
    args = _parse_args()
    try:
        asyncio.run(main(dev_mode=args.dev, config_path=args.config))
    except KeyboardInterrupt:
        log.info("Interrupted by user")
