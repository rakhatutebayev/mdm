from __future__ import annotations

import logging
import random
import subprocess
import threading
import time

from config import AgentConfig, UNINSTALL_REGISTRY_KEY
from modules.mdm import MdmAgentClient
from modules.mqtt_listener import MqttListener, mark_seen


def _next_due(now: float, interval: int) -> float:
    # Small jitter prevents many agents from hammering the server at the same second.
    return now + max(5, interval) + random.uniform(0, min(5, interval * 0.1))


def _ps_single_quote(value: str) -> str:
    return value.replace("'", "''")


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
    """Download the latest agent EXE and replace the installed binary via PowerShell.

    Runs entirely in the SYSTEM context (no UAC dialog needed).
    Existing config.json is preserved — customer_id and enrollment_token remain.
    """
    import sys

    payload        = cmd.get("payload", {})
    command_id     = str(cmd.get("id", "") or "").strip()
    download_url   = payload.get("download_url", "").strip()
    target_version = payload.get("target_version", "unknown")
    expected_sha256 = str(payload.get("sha256", "") or "").strip().lower()

    if not download_url:
        return "failed", "download_url is missing in payload"
    if not expected_sha256:
        return "failed", "sha256 is missing in payload"

    # Installed EXE path — this is where the service binary lives
    installed_exe = sys.executable  # service runs from the installed location

    try:
        checksum_block = ""
        if expected_sha256:
            checksum_block = (
                f"$expectedHash = '{_ps_single_quote(expected_sha256)}'\n"
                "    if ($expectedHash) {\n"
                "        $actualHash = (Get-FileHash -Path $tempExe -Algorithm SHA256).Hash.ToLowerInvariant()\n"
                "        if ($actualHash -ne $expectedHash) { throw \"SHA256 mismatch. expected=$expectedHash actual=$actualHash\" }\n"
                "    }\n"
            )
        # PowerShell script:
        # 1. Download new EXE to a temp file
        # 1.1 Verify checksum if provided
        # 1.2 Update config.json version so telemetry reflects the new binary
        # 2. Stop the service (graceful)
        # 3. Overwrite the installed binary
        # 4. Start the service again
        # Running as SYSTEM so no UAC or ShellExecute needed.
        ps_script = f"""
$ErrorActionPreference = 'Stop'
$tempExe = [System.IO.Path]::GetTempFileName() + '.exe'
$configPath = '{_ps_single_quote(str(AgentConfig.config_path()))}'
$uninstallRegPath = 'HKLM:\\{_ps_single_quote(UNINSTALL_REGISTRY_KEY)}'
$commandId = '{_ps_single_quote(command_id)}'
$ackUrl = '{_ps_single_quote(config.server_url.rstrip("/") + "/api/v1/mdm/windows/commands/ack")}'

function Send-Ack([string]$status, [string]$result) {{
    if (-not $commandId -or -not $ackUrl) {{
        return
    }}
    try {{
        $body = @{{
            command_id = $commandId
            status = $status
            result = $result
        }} | ConvertTo-Json -Compress
        Invoke-RestMethod -Uri $ackUrl -Method Post -ContentType 'application/json' -Body $body | Out-Null
    }} catch {{
        # Best effort only. If ack delivery fails, the command will be retried.
    }}
}}

try {{
    # Download new agent
    $wc = New-Object System.Net.WebClient
    $wc.Headers.Add('User-Agent', 'NOCKO-Agent/{_ps_single_quote(target_version)}-updater')
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $wc.DownloadFile('{_ps_single_quote(download_url)}', $tempExe)

    {checksum_block}

    # Stop current service gracefully
    Stop-Service -Name 'NOCKOAgent' -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 3

    # Replace binary
    Copy-Item -Path $tempExe -Destination '{_ps_single_quote(str(installed_exe))}' -Force

    if (Test-Path $configPath) {{
        $config = Get-Content -Raw -Path $configPath | ConvertFrom-Json
        $config.agent_version = '{_ps_single_quote(str(target_version))}'
        $config | ConvertTo-Json -Depth 8 | Set-Content -Path $configPath -Encoding UTF8
    }}

    if (Test-Path $uninstallRegPath) {{
        Set-ItemProperty -Path $uninstallRegPath -Name 'DisplayVersion' -Value '{_ps_single_quote(str(target_version))}'
    }}

    # Start updated service
    Start-Service -Name 'NOCKOAgent' -ErrorAction SilentlyContinue
    Send-Ack 'acked' 'Update installed successfully.'
}} catch {{
    $message = $_.Exception.Message
    Send-Ack 'failed' $message
    throw
}} finally {{
    Remove-Item -Path $tempExe -Force -ErrorAction SilentlyContinue
}}
"""
        import subprocess
        proc = subprocess.Popen(
            ["powershell", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        # Don't wait — the updater process will stop the service, replace the
        # binary, start it again, and send the final command ack itself.
        logger.info("Update to v%s started via PowerShell (pid=%s)", target_version, proc.pid)
        return "deferred", f"Update to v{target_version} started. Final status will be reported after restart."

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
            if status == "deferred":
                logger.info("Command '%s' is running asynchronously: %s", cmd_type, result_msg)
                continue
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
