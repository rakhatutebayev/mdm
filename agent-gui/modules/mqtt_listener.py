"""MQTT listener for the NOCKO MDM Windows agent.

Subscribes to mdm/devices/{device_id}/commands and instantly dispatches
commands through the same _dispatch_commands pipeline used by HTTP polling.
Deduplication prevents running a command twice if both MQTT and HTTP deliver it.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from config import AgentConfig

log = logging.getLogger("mqtt_listener")

# ── Deduplication ─────────────────────────────────────────────────────────────
# Keep the last 200 executed command IDs so we never run one twice
_seen_ids: deque[str] = deque(maxlen=200)
_seen_lock = threading.Lock()


def mark_seen(command_id: str) -> bool:
    """Return True if this command_id is NEW (not seen before) and mark it seen."""
    with _seen_lock:
        if command_id in _seen_ids:
            return False
        _seen_ids.append(command_id)
        return True


# ── MQTT Listener ─────────────────────────────────────────────────────────────

class MqttListener:
    """Background thread that maintains a persistent MQTT connection."""

    def __init__(self, config: "AgentConfig", dispatch_fn, client_ref=None):
        self._config = config
        self._dispatch = dispatch_fn   # _dispatch_commands from service_runtime
        self._client_ref = client_ref  # MdmAgentClient for inventory push
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()

    # ── derive broker host from server_url if mqtt_host not set ──────────────
    def _broker_host(self) -> str:
        host = getattr(self._config, "mqtt_host", "")
        if host:
            return host
        url = self._config.server_url.rstrip("/")
        for scheme in ("https://", "http://"):
            if url.startswith(scheme):
                url = url[len(scheme):]
        return url.split("/")[0]

    def _use_tls(self) -> bool:
        """Use TLS if server_url starts with https and no explicit mqtt_host override."""
        explicit_host = getattr(self._config, "mqtt_host", "")
        if explicit_host:
            return False  # explicit host — don't assume TLS
        return self._config.server_url.startswith("https://")

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="mqtt-listener")
        self._thread.start()
        log.info("MQTT listener thread started")

    def stop(self) -> None:
        self._stop.set()

    def _configure_tls(self, client, insecure: bool) -> None:
        import ssl as _ssl

        cert_reqs = _ssl.CERT_NONE if insecure else _ssl.CERT_REQUIRED
        client.tls_set(cert_reqs=cert_reqs)
        client.tls_insecure_set(insecure)

    @staticmethod
    def _looks_like_tls_error(exc: Exception) -> bool:
        message = str(exc).lower()
        return any(token in message for token in (
            "ssl",
            "tls",
            "certificate",
            "cert",
            "hostname mismatch",
            "self signed",
            "verify failed",
        ))

    def _run(self) -> None:
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except ImportError:
            log.warning("paho-mqtt not installed — MQTT listener disabled. Using HTTP polling only.")
            return

        host      = self._broker_host()
        port      = getattr(self._config, "mqtt_port",      443)
        transport = getattr(self._config, "mqtt_transport", "websockets")
        ws_path   = getattr(self._config, "mqtt_path",      "/mqtt")
        use_tls   = getattr(self._config, "mqtt_tls",       self._use_tls())
        verify_tls = bool(getattr(self._config, "mqtt_tls_verify", True))
        allow_insecure_fallback = bool(getattr(self._config, "mqtt_tls_allow_insecure_fallback", False))
        device_id = self._config.device_id
        topic = f"mdm/devices/{device_id}/commands"
        backoff = 5
        insecure_tls_active = use_tls and not verify_tls

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                client.subscribe(topic, qos=1)
                log.info("MQTT connected → subscribed to %s (transport=%s)", topic, transport)
            else:
                log.warning("MQTT connect failed rc=%s", rc)

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload)
                cmd_id = payload.get("id", "")
                if not mark_seen(cmd_id):
                    log.debug("MQTT: duplicate command %s — skipped", cmd_id)
                    return
                log.info("MQTT command received: %s (id=%s)", payload.get("type"), cmd_id)
                self._dispatch([payload], self._config, self._client_ref)
            except Exception as exc:
                log.exception("MQTT message processing error: %s", exc)

        while not self._stop.is_set():
            client = mqtt.Client(
                client_id=f"nocko-agent-{device_id}",
                clean_session=False,
                transport=transport,
            )
            if transport == "websockets":
                client.ws_set_options(path=ws_path)
            if use_tls:
                self._configure_tls(client, insecure=insecure_tls_active)
            client.on_connect = on_connect
            client.on_message = on_message
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            try:
                client.connect(host, port, keepalive=60)
                client.loop_start()
                backoff = 5
                # Wait until stop is signalled
                self._stop.wait()
                client.loop_stop()
                client.disconnect()
                break
            except Exception as exc:
                if use_tls and not insecure_tls_active and allow_insecure_fallback and self._looks_like_tls_error(exc):
                    insecure_tls_active = True
                    log.warning(
                        "MQTT TLS certificate verification failed for %s:%s. Falling back to insecure TLS because mqtt_tls_allow_insecure_fallback=true: %s",
                        host,
                        port,
                        exc,
                    )
                    continue
                log.warning("MQTT connect error (%s). Retrying in %ss…", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
