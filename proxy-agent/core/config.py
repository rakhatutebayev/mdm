"""
Config loader for NOCKO Proxy Agent.

LOCAL ONLY fields  — stored in config.json on this machine, never overwritten by the portal.
SERVER-MANAGED     — fetched from MDM via HTTPS GET /api/v1/agent/config and cached in SQLite.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional

_DEFAULT_CONFIG_PATH = Path(__file__).parent.parent / "config.json"


# ──────────────────────────────────────────────────────────────────────────────
# LOCAL ONLY (loaded from config.json)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class LocalConfig:
    listen_host: str = "0.0.0.0"
    listen_port: int = 8443
    log_level: str = "INFO"
    mdm_url: str = ""
    enrollment_token: str = ""
    data_dir: str = "/var/lib/nocko-agent"
    cert_dir: str = "/etc/nocko-agent/certs"
    db_path: str = "/var/lib/nocko-agent/agent.db"
    # Local Web Console: use TLS when cert/key exist under cert_dir (install.sh creates ui.crt/ui.key)
    console_tls: bool = True
    console_cert_filename: str = "ui.crt"
    console_key_filename: str = "ui.key"
    # PEM file under cert_dir; bundled by install.sh as mdm-ca.pem. Empty = use OS trust store only.
    mdm_trust_ca_file: str = "mdm-ca.pem"


# ──────────────────────────────────────────────────────────────────────────────
# SERVER-MANAGED (fetched from MDM, stored in AgentConfig table)
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class ServerConfig:
    """Populated after bootstrap; defaults used until first sync."""
    agent_id: Optional[str] = None
    tenant_id: Optional[str] = None
    site_id: Optional[str] = None
    broker_url: str = ""
    broker_port: int = 8883
    heartbeat_interval: int = 60         # seconds
    metrics_fast_interval: int = 60      # seconds  (poll_class = fast)
    metrics_slow_interval: int = 300     # seconds  (poll_class = slow)
    inventory_interval: int = 86400      # seconds  (daily)
    lld_interval: int = 3600             # seconds

    # Per-device SNMP defaults (can be overridden per device)
    snmp_version: str = "2c"
    snmp_community: str = "public"
    snmp_v3_user: str = ""
    snmp_v3_auth_proto: str = "SHA"
    snmp_v3_priv_proto: str = "AES"


# ──────────────────────────────────────────────────────────────────────────────
# Runtime container
# ──────────────────────────────────────────────────────────────────────────────
@dataclass
class AgentConfig:
    local: LocalConfig = field(default_factory=LocalConfig)
    server: ServerConfig = field(default_factory=ServerConfig)

    @property
    def db_path(self) -> str:
        return self.local.db_path

    @property
    def cert_dir(self) -> Path:
        return Path(self.local.cert_dir)

    @property
    def client_cert(self) -> Path:
        return self.cert_dir / "client.crt"

    @property
    def client_key(self) -> Path:
        return self.cert_dir / "client.key"

    @property
    def console_cert_path(self) -> Path:
        return self.cert_dir / self.local.console_cert_filename

    @property
    def console_key_path(self) -> Path:
        return self.cert_dir / self.local.console_key_filename

    @property
    def mdm_trust_ca_path(self) -> Optional[Path]:
        """Path to custom CA bundle if file exists; else None (httpx/MQTT use defaults)."""
        name = (self.local.mdm_trust_ca_file or "").strip()
        if not name:
            return None
        p = self.cert_dir / name
        return p if p.is_file() else None


# Singleton — will be populated by load_config()
config: AgentConfig = AgentConfig()


def load_config(config_path: str | Path | None = None) -> AgentConfig:
    """Load LOCAL config.json. SERVER-MANAGED fields are loaded separately after bootstrap."""
    global config

    path = Path(config_path or os.environ.get("NOCKO_CONFIG", _DEFAULT_CONFIG_PATH))
    if not path.exists():
        # Fallback: create example config and run with defaults
        import warnings
        warnings.warn(f"config.json not found at {path}. Using defaults.")
        config.local = LocalConfig()
        return config

    raw = json.loads(path.read_text(encoding="utf-8"))
    local = LocalConfig(**{k: v for k, v in raw.items() if k in LocalConfig.__dataclass_fields__})
    # Mutate singleton in place so importers that did `from core.config import config`
    # still see updated values (rebinding global `config` alone would not update those refs).
    config.local = local
    return config
