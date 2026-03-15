"""Build MSI installer using wixl (msitools).

Requires: apt install msitools  (on the Linux server)
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATE_DIR = Path(__file__).parent / "templates"
_jinja = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), keep_trailing_newline=True)


class BuildToolMissingError(RuntimeError):
    pass


def build_msi(
    *,
    customer_id: str,
    customer_name: str,
    enrollment_token: str,
    server_url: str,
    arch: str = "x64",
) -> bytes:
    """Return MSI bytes.  Requires wixl on PATH (msitools package)."""

    wixl = shutil.which("wixl")
    if not wixl:
        raise BuildToolMissingError(
            "wixl not found. Install msitools: apt install msitools"
        )

    ctx = dict(
        server_url=server_url,
        enrollment_token=enrollment_token,
        customer_id=customer_id,
        customer_name=customer_name,
        arch=arch,
        # Deterministic upgrade GUID from customer_id (full UUID5, standard 8-4-4-4-12 format)
        upgrade_guid=str(uuid.uuid5(uuid.NAMESPACE_DNS, customer_id)).upper(),
    )

    install_ps1   = _jinja.get_template("install.ps1.j2").render(**ctx)
    uninstall_ps1 = _jinja.get_template("uninstall.ps1.j2").render(**ctx)
    wxs_content   = _jinja.get_template("product.wxs.j2").render(**ctx)
    config_json  = json.dumps(
        {"server_url": server_url, "enrollment_token": enrollment_token,
         "customer_id": customer_id, "customer_name": customer_name},
        indent=2,
    )
    readme = (
        f"NOCKO MDM Agent — {customer_name}\n"
        f"Server: {server_url}\n\n"
        "Deploy this MSI via GPO, Intune, or SCCM.\n"
        "Run as Administrator: msiexec /i nocko-mdm-agent.msi /quiet\n"
    )

    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        (tmpdir / "install.ps1").write_text(install_ps1,   encoding="utf-8")
        (tmpdir / "uninstall.ps1").write_text(uninstall_ps1, encoding="utf-8")
        (tmpdir / "config.json").write_text(config_json,   encoding="utf-8")
        (tmpdir / "README.txt").write_text(readme,         encoding="utf-8")

        wxs_path = tmpdir / "product.wxs"
        wxs_path.write_text(wxs_content, encoding="utf-8")

        out_msi = tmpdir / "nocko-mdm-agent.msi"

        arch_args = ["-a", "x64"] if arch == "x64" else []
        result = subprocess.run(
            [wixl, "-v", *arch_args, "-o", str(out_msi), str(wxs_path)],
            capture_output=True,
            cwd=str(tmpdir),
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"wixl failed:\n{result.stderr.decode(errors='replace')}"
            )

        return out_msi.read_bytes()
