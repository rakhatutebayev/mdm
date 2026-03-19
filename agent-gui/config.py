from __future__ import annotations

import json
import os
import struct
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


AGENT_VERSION = (os.getenv("NOCKO_AGENT_VERSION", "") or "").strip() or "1.2.0"
WINDOWS_SERVICE_NAME = "NOCKOAgent"
EMBEDDED_CONFIG_MAGIC = b"NOCKO_CFG_V1"
UNINSTALL_REGISTRY_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\NOCKOAgent"


def _default_base_dir() -> Path:
    if os.name == "nt":
        program_data = os.getenv("PROGRAMDATA", r"C:\ProgramData")
        return Path(program_data) / "NOCKO-Agent"
    return Path.home() / ".nocko-agent"


@dataclass
class AgentConfig:
    server_url: str = "https://mdm.nocko.com"
    enrollment_token: str = ""
    customer_id: str = ""
    heartbeat_interval: int = 60
    metrics_interval: int = 120
    inventory_interval: int = 600
    commands_interval: int = 45
    mdm_enabled: bool = True
    siem_enabled: bool = False
    backup_enabled: bool = False
    remote_enabled: bool = False
    log_level: str = "INFO"
    agent_version: str = AGENT_VERSION
    device_id: str = ""
    install_dir: str = r"C:\Program Files\NOCKO MDM Agent"
    log_dir: str = r"C:\ProgramData\NOCKO-Agent\logs"
    start_immediately: bool = True
    agent_display_name: str = "NOCKO MDM Agent"
    tls_verify: bool = True
    tls_allow_insecure_fallback: bool = False
    # MQTT settings (for real-time command delivery via WebSocket/WSS)
    mqtt_enabled:   bool = True
    mqtt_host:      str  = ""         # if empty, derived from server_url hostname
    mqtt_port:      int  = 443         # 443 via WSS (Nginx proxy) or 1883 for raw TCP
    mqtt_transport: str  = "websockets" # 'websockets' or 'tcp'
    mqtt_path:      str  = "/mqtt"     # WebSocket endpoint path
    mqtt_tls:       bool = True        # True when using wss:// (port 443)
    mqtt_tls_verify: bool = True
    mqtt_tls_allow_insecure_fallback: bool = False

    @classmethod
    def base_dir(cls) -> Path:
        return _default_base_dir()

    @classmethod
    def config_path(cls) -> Path:
        return cls.base_dir() / "config.json"

    @classmethod
    def default_log_dir(cls) -> Path:
        return cls.base_dir() / "logs"

    @classmethod
    def load(cls, path: Path | None = None) -> "AgentConfig":
        config_path = path or cls.config_path()
        if not config_path.exists():
            config = cls()
            config.agent_version = resolve_agent_version(persisted_version=config.agent_version)
            config.save(config_path)
            return config

        with config_path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if "checkin_interval" in raw:
            legacy = int(raw["checkin_interval"])
            raw.setdefault("heartbeat_interval", legacy)
            raw.setdefault("metrics_interval", max(legacy, 120))
            raw.setdefault("inventory_interval", 21600)
            raw.setdefault("commands_interval", min(max(legacy // 2, 30), 300))
        defaults = asdict(cls())
        allowed = set(defaults.keys())
        merged = {**defaults, **{k: v for k, v in raw.items() if k in allowed}}
        # Existing installations previously skipped certificate verification.
        # Keep them online by allowing an insecure fallback unless the config
        # was already migrated to explicit TLS policy fields.
        if "tls_allow_insecure_fallback" not in raw:
            merged["tls_allow_insecure_fallback"] = True
        if "mqtt_tls_allow_insecure_fallback" not in raw:
            merged["mqtt_tls_allow_insecure_fallback"] = True
        merged["agent_version"] = resolve_agent_version(
            persisted_version=str(raw.get("agent_version", "") or ""),
        )
        return cls(**merged)  # type: ignore[arg-type]

    def save(self, path: Path | None = None) -> Path:
        config_path = path or self.config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as fh:
            json.dump(asdict(self), fh, indent=2)
            fh.write("\n")
        return config_path


def load_config(path: str | None = None) -> AgentConfig:
    return AgentConfig.load(Path(path) if path else None)


def _read_embedded_footer(executable_path: str | Path) -> tuple[int, int] | None:
    path = Path(executable_path)
    if not path.exists():
        return None

    with path.open("rb") as fh:
        fh.seek(0, 2)
        size = fh.tell()
        footer_size = len(EMBEDDED_CONFIG_MAGIC) + 8
        if size < footer_size:
            return None

        fh.seek(-footer_size, 2)
        footer = fh.read(footer_size)
        if not footer.endswith(EMBEDDED_CONFIG_MAGIC):
            return None

        payload_size = struct.unpack("<Q", footer[:8])[0]
        if payload_size <= 0 or payload_size > size - footer_size:
            return None

        return payload_size, footer_size


def read_embedded_config(executable_path: str | Path) -> dict | None:
    footer = _read_embedded_footer(executable_path)
    if not footer:
        return None

    payload_size, footer_size = footer
    path = Path(executable_path)
    with path.open("rb") as fh:
        fh.seek(-(footer_size + payload_size), 2)
        payload = fh.read(payload_size)
    return json.loads(payload.decode("utf-8"))


def resolve_agent_version(
    executable_path: str | Path | None = None,
    persisted_version: str | None = None,
) -> str:
    """Resolve the effective runtime agent version.

    Priority:
    1. Explicit environment override during build/test.
    2. Embedded bootstrap config from the current executable.
    3. Persisted config.json version written at install/update time.
    4. Fallback constant for legacy/manual runs.
    """
    env_version = (os.getenv("NOCKO_AGENT_VERSION", "") or "").strip()
    if env_version:
        return env_version

    exe_path = Path(executable_path) if executable_path else Path(sys.executable)
    embedded = read_embedded_config(exe_path)
    embedded_version = str((embedded or {}).get("agent_version", "") or "").strip()
    if embedded_version:
        return embedded_version

    persisted = str(persisted_version or "").strip()
    if persisted:
        return persisted

    return AGENT_VERSION


def write_executable_without_embedded_config(source_path: str | Path, target_path: str | Path) -> bool:
    footer = _read_embedded_footer(source_path)
    source = Path(source_path)
    target = Path(target_path)

    if not footer:
        target.write_bytes(source.read_bytes())
        return False

    payload_size, footer_size = footer
    base_size = source.stat().st_size - payload_size - footer_size
    with source.open("rb") as src, target.open("wb") as dst:
        dst.write(src.read(base_size))
    return True
