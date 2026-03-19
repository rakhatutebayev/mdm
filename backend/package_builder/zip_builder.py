"""Build ZIP package (Scripts + Agent).

Works on any OS — pure Python stdlib.
"""
from __future__ import annotations
import json
import zipfile
from io import BytesIO
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), keep_trailing_newline=True)


def build_zip(
    *,
    customer_id: str,
    customer_name: str,
    enrollment_token: str,
    server_url: str,
    arch: str = "x64",
    install_mode: str = "silent",  # accepted but unused for ZIP (no installer UI)
    agent_display_name: str = "NOCKO MDM Agent",
    install_dir: str = r"C:\Program Files\NOCKO MDM\Agent",
    log_dir: str = r"C:\ProgramData\NOCKO MDM\logs",
    register_scheduled_task: bool = True,
    start_immediately: bool = True,
    heartbeat_interval: int = 60,
    metrics_interval: int = 120,
    inventory_interval: int = 21600,
    commands_interval: int = 45,
    log_level: str = "INFO",
    siem_enabled: bool = False,
    agent_version: str = "",
) -> bytes:
    """Return ZIP file bytes containing install.ps1, config.json, README.txt."""

    ctx = dict(
        server_url=server_url,
        enrollment_token=enrollment_token,
        customer_id=customer_id,
        customer_name=customer_name,
        arch=arch,
        install_mode=install_mode,
        agent_display_name=agent_display_name,
        install_dir=install_dir,
        log_dir=log_dir,
        register_scheduled_task=register_scheduled_task,
        start_immediately=start_immediately,
        agent_version=agent_version,
    )

    install_ps1 = _jinja.get_template("install.ps1.j2").render(**ctx)

    config_json = json.dumps(
        {
            "server_url": server_url,
            "enrollment_token": enrollment_token,
            "customer_id": customer_id,
            "customer_name": customer_name,
            "heartbeat_interval": heartbeat_interval,
            "metrics_interval": metrics_interval,
            "inventory_interval": inventory_interval,
            "commands_interval": commands_interval,
            "mdm_enabled": True,
            "siem_enabled": siem_enabled,
            "backup_enabled": False,
            "remote_enabled": False,
            "log_level": log_level,
            "agent_version": agent_version,
            "device_id": "",
            "install_dir": install_dir,
            "log_dir": log_dir,
            "start_immediately": start_immediately,
            "agent_display_name": agent_display_name,
        },
        indent=2,
    )

    readme = _readme(customer_name, server_url)

    buf = BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("install.ps1",  install_ps1)
        zf.writestr("config.json",  config_json)
        zf.writestr("README.txt",   readme)
    return buf.getvalue()


def _readme(customer_name: str, server_url: str) -> str:
    return f"""\
NOCKO MDM — Windows Agent Enrollment Package
============================================
Customer : {customer_name}
Server   : {server_url}

INSTALLATION
------------
1. Extract this ZIP to any folder.
2. Open PowerShell as Administrator.
3. Run:
       Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
       .\\install.ps1

The script will:
  - Collect device information
  - Register the device with the MDM server
  - Write agent config to C:\\ProgramData\\NOCKO MDM\\
  - Register a scheduled check-in task (every 15 min)

SUPPORT
-------
docs: https://nocko.com/mdm/docs
"""
