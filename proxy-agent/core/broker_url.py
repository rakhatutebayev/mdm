"""
Normalize MQTT broker URLs returned by MDM for site-installed proxy agents.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse

from core.logger import log


def normalize_broker_url_from_mdm(url: str) -> str:
    """
    MDM may return mqtt://mdm.example:1883 (reachable only inside Docker). Site agents
    use WSS on :443 (nginx → EMQX). Rewrite plain mqtt + port 1883 only.

    Disable: NOCKO_MQTT_BROKER_RAW=1. Custom path: NOCKO_MQTT_WSS_PATH (default /mqtt).
    """
    if os.getenv("NOCKO_MQTT_BROKER_RAW", "").strip() == "1":
        return url
    raw = (url or "").strip()
    if not raw:
        return raw
    u = urlparse(raw)
    if u.scheme != "mqtt":
        return raw
    port = u.port if u.port is not None else 1883
    if port != 1883:
        return raw
    host = (u.hostname or "").strip().lower()
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return raw
    path = (os.getenv("NOCKO_MQTT_WSS_PATH") or "/mqtt").strip()
    if not path.startswith("/"):
        path = "/" + path
    fixed = f"wss://{host}{path}"
    if fixed != raw:
        log.info(f"Broker URL normalized for site reachability: {raw!r} -> {fixed!r}")
    return fixed
