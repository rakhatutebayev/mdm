"""
NOCKO Agent — Configuration Manager
Reads/writes config from %ProgramData%/NOCKO-Agent/config.json (Windows)
or ~/.nocko-agent/config.json (dev/macOS).
"""
import json
import os
import platform
from pathlib import Path

_DEFAULTS = {
    # ── Server ──────────────────────────────────────────────────────────────
    # Only set 'server_host' — the full API URL is derived automatically.
    # Format: hostname or hostname:port  (no scheme, no trailing slash)
    "server_host":       "mdm.it-uae.com",
    "server_scheme":     "https",          # "https" or "http" (dev only)
    "api_prefix":        "/api/v1",        # rarely needs changing

    # ── MDM ─────────────────────────────────────────────────────────────────
    "enrollment_token":  "",
    "checkin_interval":  15,               # minutes

    # ── SIEM ────────────────────────────────────────────────────────────────
    "siem_enabled":      True,
    "siem_interval":     5,                # minutes

    # ── Future modules ───────────────────────────────────────────────────────
    "backup_enabled":    False,
    "remote_enabled":    False,

    # ── General ─────────────────────────────────────────────────────────────
    "agent_version":     "1.0.0",
    "log_level":         "INFO",
}


def _config_path() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("ProgramData", "C:/ProgramData"))
        return base / "NOCKO-Agent" / "config.json"
    # macOS / Linux (dev)
    return Path.home() / ".nocko-agent" / "config.json"


class Config:
    def __init__(self):
        self._path = _config_path()
        self._data: dict = {}
        self.load()

    def load(self):
        self._data = dict(_DEFAULTS)
        if self._path.exists():
            try:
                with open(self._path, "r", encoding="utf-8") as f:
                    saved = json.load(f)
                self._data.update(saved)
            except Exception:
                pass

    def save(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def set(self, key: str, value):
        self._data[key] = value
        self.save()

    def all(self) -> dict:
        return dict(self._data)

    # Convenience properties
    @property
    def server_host(self)      -> str:  return self._data["server_host"]
    @property
    def server_scheme(self)    -> str:  return self._data.get("server_scheme", "https")
    @property
    def api_prefix(self)       -> str:  return self._data.get("api_prefix", "/api/v1")
    @property
    def mdm_server(self)       -> str:
        """Full API base URL derived from server_host."""
        return f"{self.server_scheme}://{self.server_host}{self.api_prefix}"
    @property
    def enrollment_token(self) -> str:  return self._data["enrollment_token"]
    @property
    def checkin_interval(self) -> int:  return int(self._data["checkin_interval"])
    @property
    def siem_enabled(self)     -> bool: return bool(self._data["siem_enabled"])
    @property
    def siem_interval(self)    -> int:  return int(self._data["siem_interval"])
    @property
    def backup_enabled(self)   -> bool: return bool(self._data["backup_enabled"])
    @property
    def remote_enabled(self)   -> bool: return bool(self._data["remote_enabled"])
    @property
    def agent_version(self)    -> str:  return self._data["agent_version"]


# Global singleton
config = Config()
