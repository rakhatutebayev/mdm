"""Build EXE installer using NSIS (makensis).

Requires: apt install nsis  (on the Linux server)
On macOS/Windows the function raises BuildToolMissingError with instructions.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), keep_trailing_newline=True)


class BuildToolMissingError(RuntimeError):
    pass


def build_exe(
    *,
    customer_id: str,
    customer_name: str,
    enrollment_token: str,
    server_url: str,
    arch: str = "x64",
) -> bytes:
    """Return EXE bytes.  Requires makensis on PATH."""

    makensis = shutil.which("makensis")
    if not makensis:
        raise BuildToolMissingError(
            "makensis not found. Install NSIS: apt install nsis"
        )

    ctx = dict(
        server_url=server_url,
        enrollment_token=enrollment_token,
        customer_id=customer_id,
        customer_name=customer_name,
        arch=arch,
    )

    install_ps1 = _jinja.get_template("install.ps1.j2").render(**ctx)
    nsi_script  = _jinja.get_template("setup.nsi.j2").render(**ctx)
    config_json = json.dumps(
        {"server_url": server_url, "enrollment_token": enrollment_token,
         "customer_id": customer_id, "customer_name": customer_name},
        indent=2,
    )
    readme = _readme(customer_name, server_url)

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "install.ps1").write_text(install_ps1, encoding="utf-8")
        (tmpdir / "config.json").write_text(config_json, encoding="utf-8")
        (tmpdir / "README.txt").write_text(readme,       encoding="utf-8")

        nsi_path = tmpdir / "setup.nsi"
        nsi_path.write_text(nsi_script, encoding="utf-8")

        out_exe = tmpdir / "nocko-mdm-agent-setup.exe"

        result = subprocess.run(
            [makensis, "-V2", str(nsi_path)],
            capture_output=True,
            cwd=str(tmpdir),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"makensis failed:\n{result.stderr.decode(errors='replace')}"
            )

        return out_exe.read_bytes()


def _readme(customer_name: str, server_url: str) -> str:
    return (
        f"NOCKO MDM Agent — {customer_name}\n"
        f"Server: {server_url}\n\n"
        "Run setup.exe as Administrator to enroll this device.\n"
    )
