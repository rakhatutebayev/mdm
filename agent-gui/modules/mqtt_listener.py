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
        # Extract hostname from server_url e.g. https://mdm.nocko.com → mdm.nocko.com
        url = self._config.server_url.rstrip("/")
        for scheme in ("https://", "http://"):
            if url.startswith(scheme):
                url = url[len(scheme):]
        return url.split("/")[0]

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name="mqtt-listener")
        self._thread.start()
        log.info("MQTT listener thread started")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except ImportError:
            log.warning("paho-mqtt not installed — MQTT listener disabled. Using HTTP polling only.")
            return

        host = self._broker_host()
        port = getattr(self._config, "mqtt_port", 1883)
        device_id = self._config.device_id
        topic = f"mdm/devices/{device_id}/commands"
        backoff = 5

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                client.subscribe(topic, qos=1)
                log.info("MQTT connected → subscribed to %s", topic)
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
                # Wrap in list to match _dispatch_commands signature
                self._dispatch([payload], self._config, self._client_ref)
            except Exception as exc:
                log.exception("MQTT message processing error: %s", exc)

        while not self._stop.is_set():
            client = mqtt.Client(
                client_id=f"nocko-agent-{device_id}",
                clean_session=False,
            )
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
                log.warning("MQTT connect error (%s). Retrying in %ss…", exc, backoff)
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
