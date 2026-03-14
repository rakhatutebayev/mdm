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
) -> bytes:
    """Return ZIP file bytes containing install.ps1, config.json, README.txt."""

    ctx = dict(
        server_url=server_url,
        enrollment_token=enrollment_token,
        customer_id=customer_id,
        customer_name=customer_name,
        arch=arch,
    )

    install_ps1 = _jinja.get_template("install.ps1.j2").render(**ctx)

    config_json = json.dumps(
        {
            "server_url": server_url,
            "enrollment_token": enrollment_token,
            "customer_id": customer_id,
            "customer_name": customer_name,
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
