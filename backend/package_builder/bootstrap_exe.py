"""Create a customer-specific single-file EXE by appending bootstrap config."""
from __future__ import annotations

import json
import struct


EMBEDDED_CONFIG_MAGIC = b"NOCKO_CFG_V1"


def embed_bootstrap_config(base_exe: bytes, config: dict) -> bytes:
    """Append bootstrap JSON to a base EXE.

    The Windows agent reads the trailing payload at runtime and installs itself
    with the embedded tenant-specific settings.
    """
    payload = json.dumps(config, separators=(",", ":"), ensure_ascii=True).encode("utf-8")
    footer = struct.pack("<Q", len(payload)) + EMBEDDED_CONFIG_MAGIC
    return base_exe + payload + footer
