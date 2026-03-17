from __future__ import annotations

import logging
import random
import subprocess
import threading
import time

from config import AgentConfig
from modules.mdm import MdmAgentClient
from modules.mqtt_listener import MqttListener, mark_seen


def _next_due(now: float, interval: int) -> float:
    # Small jitter prevents many agents from hammering the server at the same second.
    return now + max(5, interval) + random.uniform(0, min(5, interval * 0.1))


# ── Command handlers ──────────────────────────────────────────────────────────

def _handle_rename_computer(
    cmd: dict, config: AgentConfig, logger: logging.Logger,
    client: "MdmAgentClient | None" = None,
) -> tuple[str, str]:
    """Rename this Windows computer. Returns (status, result_message)."""
    payload = cmd.get("payload", {})
    new_name: str = payload.get("new_name", "").strip()
    restart_after: bool = bool(payload.get("restart_after", True))

    if not new_name:
        return "failed", "new_name is empty"

    try:
        # Use PowerShell — works on all Windows versions
        result = subprocess.run(
            ["powershell", "-NonInteractive", "-Command",
             f"Rename-Computer -NewName '{new_name}' -Force"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.strip() or result.stdout.strip()
            return "failed", f"Rename-Computer failed (rc={result.returncode}): {err}"

        logger.info("Computer renamed to '%s' successfully", new_name)

        # Push inventory immediately so the portal reflects the new name right away.
        # We temporarily patch socket.gethostname so collect_inventory_payload picks
        # up the new name before the OS restart applies it.
        if client is not None:
            try:
                import socket as _socket
                _orig_gethostname = _socket.gethostname
                _socket.gethostname = lambda: new_name  # type: ignore[assignment]
                try:
                    client.send_inventory()
                    logger.info("Inventory pushed with new name '%s'", new_name)
                finally:
                    _socket.gethostname = _orig_gethostname  # type: ignore[assignment]
            except Exception as inv_exc:
                logger.warning("Immediate inventory push failed (non-fatal): %s", inv_exc)

        if restart_after:
            # Delayed restart so the agent can ack the command first
            subprocess.Popen(
                ["powershell", "-NonInteractive", "-Command",
                 "Start-Sleep 10; Restart-Computer -Force"],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return "acked", f"Renamed to '{new_name}'. Restarting in 10 seconds."

        return "acked", f"Renamed to '{new_name}'. Restart required to apply."

    except Exception as exc:
        logger.exception("rename_computer error: %s", exc)
        return "failed", str(exc)


def _handle_update_agent(cmd: dict, config: AgentConfig, logger: logging.Logger) -> tuple[str, str]:
    """Download the latest agent EXE and re-run it elevated to self-update.

    ACKs immediately — the current process will be killed when the new installer
    stops/removes the old Windows service.
    """
    import ctypes
    import os
    import tempfile
    import urllib.request

    payload      = cmd.get("payload", {})
    download_url: str   = payload.get("download_url", "").strip()
    target_version: str = payload.get("target_version", "unknown")

    if not download_url:
        return "failed", "download_url is missing in payload"

    try:
        import ssl

        logger.info("Downloading agent update v%s from %s", target_version, download_url)
        tmp_dir  = tempfile.mkdtemp(prefix="nocko_update_")
        exe_path = os.path.join(tmp_dir, f"nocko-agent-{target_version}.exe")

        # Skip SSL verification — Windows Python often lacks corporate CA bundle
        ssl_ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(download_url, context=ssl_ctx, timeout=120) as resp:
            with open(exe_path, "wb") as f:
                f.write(resp.read())
        logger.info("Downloaded %d bytes to %s", os.path.getsize(exe_path), exe_path)

        # Launch elevated — new EXE detects existing install and reinstalls
        ret = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", exe_path, None, None, 1
        )
        if ret <= 32:
            return "failed", f"ShellExecuteW failed (ret={ret})"

        return "acked", f"Update to v{target_version} started. Agent will restart shortly."

    except Exception as exc:
        logger.exception("update_agent error: %s", exc)
        return "failed", str(exc)


def _handle_restart_agent(
    cmd: dict, config: AgentConfig, logger: logging.Logger,
    client: "MdmAgentClient | None" = None,
) -> tuple[str, str]:
    """Restart the NOCKO MDM agent service.

    Before restarting, pushes a full inventory so the portal is up to date.
    On startup the agent loop sets next_inventory=now, so inventory is sent
    immediately after the restart as well.
    """
    # Push a fresh inventory snapshot before the restart
    if client is not None:
        try:
            client.send_inventory()
            logger.info("Pre-restart inventory pushed successfully")
        except Exception as exc:
            logger.warning("Pre-restart inventory push failed (non-fatal): %s", exc)

    try:
        # Prefer restarting the Windows service (runs in elevated SYSTEM context)
        ps_cmd = (
            "Start-Sleep 5; "
            "Restart-Service -Name 'NOCKOAgent' -Force -ErrorAction SilentlyContinue; "
            # Fallback: trigger the scheduled task directly if service is not installed
            "if (-not (Get-Service 'NOCKOAgent' -ErrorAction SilentlyContinue)) { "
            "  Start-ScheduledTask -TaskName 'NOCKO MDM Agent Check-In' -ErrorAction SilentlyContinue; "
            "}"
        )
        subprocess.Popen(
            ["powershell", "-NonInteractive", "-Command", ps_cmd],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        return "acked", "Agent restart scheduled in 5 seconds. Full inventory will be sent on next checkin."
    except Exception as exc:
        logger.exception("restart_agent error: %s", exc)
        return "failed", str(exc)


_COMMAND_HANDLERS = {
    "rename_computer": _handle_rename_computer,
    "update_agent":    _handle_update_agent,
    "restart_agent":   _handle_restart_agent,
}


def _dispatch_commands(commands: list[dict], client: MdmAgentClient,
                       config: AgentConfig, logger: logging.Logger) -> None:
    for cmd in commands:
        cmd_id = cmd.get("id", "")
        cmd_type = cmd.get("type", "")
        handler = _COMMAND_HANDLERS.get(cmd_type)
        if not handler:
            logger.warning("Unknown command type '%s' — ignoring", cmd_type)
            client.ack_command(cmd_id, status="failed", result=f"Unknown command type: {cmd_type}")
            continue

        logger.info("Executing command '%s' (id=%s)", cmd_type, cmd_id)
        try:
            # Pass client to handlers that need to push data back to the server
            import inspect as _inspect
            sig = _inspect.signature(handler)
            if "client" in sig.parameters:
                status, result_msg = handler(cmd, config, logger, client=client)
            else:
                status, result_msg = handler(cmd, config, logger)
            client.ack_command(cmd_id, status=status, result=result_msg)
            logger.info("Command '%s' → %s: %s", cmd_type, status, result_msg)
        except Exception as exc:
            logger.exception("Command '%s' dispatch error: %s", cmd_type, exc)
            client.ack_command(cmd_id, status="failed", result=str(exc))


# ── Main agent loop ───────────────────────────────────────────────────────────

def run_agent_loop(
    config: AgentConfig,
    logger: logging.Logger,
    stop_event: threading.Event,
) -> None:
    client = MdmAgentClient(config, logger)
    logger.info(
        "Agent loop started heartbeat=%ss metrics=%ss inventory=%ss commands=%ss",
        config.heartbeat_interval,
        config.metrics_interval,
        config.inventory_interval,
        config.commands_interval,
    )

    client.enroll_if_needed()

    # ── Start MQTT listener (instant command delivery) ────────────────────────
    mqtt_listener: MqttListener | None = None
    if getattr(config, "mqtt_enabled", True):
        def _mqtt_dispatch(commands, cfg, cli):
            """Adapter: MqttListener calls with (commands, config, client)."""
            _dispatch_commands(commands, cli, cfg, logger)

        mqtt_listener = MqttListener(config, _mqtt_dispatch, client_ref=client)
        mqtt_listener.start()
    else:
        logger.info("MQTT listener disabled by config — using HTTP polling only")

    now = time.monotonic()
    next_heartbeat = now
    next_metrics   = now
    next_inventory = now
    next_commands  = now

    while not stop_event.is_set():
        now = time.monotonic()

        if now >= next_heartbeat:
            try:
                client.heartbeat()
            except Exception as exc:
                logger.exception("Heartbeat failed: %s", exc)
            next_heartbeat = _next_due(now, int(config.heartbeat_interval))

        if now >= next_metrics:
            try:
                client.send_metrics()
            except Exception as exc:
                logger.exception("Metrics upload failed: %s", exc)
            next_metrics = _next_due(now, int(config.metrics_interval))

        if now >= next_inventory:
            try:
                client.send_inventory()
            except Exception as exc:
                logger.exception("Inventory upload failed: %s", exc)
            next_inventory = _next_due(now, int(config.inventory_interval))

        if now >= next_commands:
            try:
                commands = client.fetch_commands()
                if commands:
                    # Deduplicate: skip commands already delivered via MQTT
                    new_cmds = [c for c in commands if mark_seen(c.get("id", ""))]
                    if new_cmds:
                        _dispatch_commands(new_cmds, client, config, logger)
            except Exception as exc:
                logger.exception("Command polling failed: %s", exc)
            next_commands = _next_due(now, int(config.commands_interval))

        wait_for = max(
            1.0,
            min(next_heartbeat, next_metrics, next_inventory, next_commands) - time.monotonic(),
        )
        stop_event.wait(wait_for)

    if mqtt_listener:
        mqtt_listener.stop()
    logger.info("Agent loop stopped")
