"""
MQTT client for NOCKO Proxy Agent.

Transport: TCP MQTT / MQTTS / MQTT over WebSocket (WS/WSS), paho-mqtt 2.x.
  - Plain: mqtt://host:1883
  - TLS:   mqtts://host:8883 or wss://host/mqtt (port 443, same TLS as HTTPS)
Auth: mTLS client certificate (after bootstrap), when cert files exist.

Data Plane topics (publish):
  nocko/{tenant_id}/{agent_id}/inventory
  nocko/{tenant_id}/{agent_id}/metrics.fast
  nocko/{tenant_id}/{agent_id}/metrics.slow
  nocko/{tenant_id}/{agent_id}/events
  nocko/{tenant_id}/{agent_id}/agent_presence  ← heartbeat (QoS 0)

Control Plane topics (subscribe):
  nocko/{tenant_id}/{agent_id}/commands
  nocko/{tenant_id}/{agent_id}/config          ← signal only (re-fetch via HTTPS)

Based on proxy_agent_tz.md Section 2.7.3.
"""
from __future__ import annotations

import asyncio
import json
import ssl
import time
from typing import Callable, Optional
from urllib.parse import urlparse

import paho.mqtt.client as mqtt

from core.config import config
from core.database import kv_get
from core.logger import log
from core import queue as q

# Callback type for incoming commands
CommandCallback = Callable[[dict], None]


def _parse_mqtt_broker_url(url: str) -> Optional[dict]:
    """
    Parse broker URL for paho.

    Returns dict: transport tcp|websockets, host, port, path (for WS), use_tls (broker TLS).
    """
    if not url or not url.strip():
        return None
    u = urlparse(url.strip())
    scheme = (u.scheme or "mqtt").lower()
    host = u.hostname
    if not host:
        return None

    if scheme in ("wss", "ws"):
        path = u.path or "/mqtt"
        if not path.startswith("/"):
            path = "/" + path
        default_port = 443 if scheme == "wss" else 80
        port = u.port if u.port is not None else default_port
        return {
            "transport": "websockets",
            "host": host,
            "port": port,
            "path": path,
            "use_tls": scheme == "wss",
        }

    if scheme in ("mqtts", "mqtt"):
        default_port = 8883 if scheme == "mqtts" else 1883
        port = u.port if u.port is not None else default_port
        return {
            "transport": "tcp",
            "host": host,
            "port": port,
            "path": "",
            "use_tls": scheme == "mqtts",
        }

    log.warning(f"Unknown MQTT URL scheme {scheme!r}, expected mqtt/mqtts/ws/wss")
    return None


class MQTTClient:
    """Wraps paho-mqtt with auto-reconnect and async-compatible publish."""

    def __init__(self) -> None:
        self._client: Optional[mqtt.Client] = None
        self._connected = False
        self._command_callback: Optional[CommandCallback] = None
        self._config_signal_callback: Optional[Callable[[], None]] = None
        self._tenant_id: str = ""
        self._agent_id: str = ""
        self._broker_parsed: Optional[dict] = None

    # ──────────────────────────────────────────────────────────────────────────
    # Setup
    # ──────────────────────────────────────────────────────────────────────────
    def setup(self) -> None:
        """Build paho client (TCP or WebSocket + optional TLS). Call before connect()."""
        self._tenant_id = kv_get("tenant_id", "")
        self._agent_id = kv_get("agent_id", "")

        broker_url = (kv_get("broker_url", "") or config.server.broker_url or "").strip()
        parsed = _parse_mqtt_broker_url(broker_url) if broker_url else None
        self._broker_parsed = parsed

        client_id = f"nocko-agent-{self._agent_id}"
        transport = "websockets" if parsed and parsed["transport"] == "websockets" else "tcp"
        self._client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv5, transport=transport)

        if transport == "websockets" and parsed:
            self._client.ws_set_options(path=parsed["path"])
            log.info(f"MQTT over WebSocket path={parsed['path']!r}")

        cert = config.client_cert
        key = config.client_key
        ca = config.mdm_trust_ca_path

        # TLS only for WSS/MQTTS or when presenting a client cert (mTLS)
        scheme_tls = bool(parsed and parsed.get("use_tls"))
        client_mtls = cert.exists() and key.exists()
        need_tls = scheme_tls or client_mtls
        if need_tls:
            ctx = ssl.create_default_context()
            if ca and ca.is_file():
                ctx.load_verify_locations(cafile=str(ca))
                log.info(f"MQTT TLS trust anchor: {ca}")
            if client_mtls:
                ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))
                log.info("MQTT mTLS client certificate configured")
            elif scheme_tls:
                log.warning("MQTT client cert not found — WSS/MQTTS without client cert (dev)")
            self._client.tls_set_context(ctx)
        else:
            log.debug("MQTT plain TCP (no TLS context)")

        # Callbacks
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

    def connect(self) -> None:
        """Connect to the MQTT broker. Reconnects automatically on failure."""
        broker_url = (kv_get("broker_url", "") or config.server.broker_url or "").strip()

        if not broker_url:
            log.error("MQTT broker_url not set. Run bootstrap first.")
            return

        parsed = _parse_mqtt_broker_url(broker_url)
        if not parsed:
            log.error(f"Invalid MQTT broker_url: {broker_url!r}")
            return

        # Recreate client if URL transport changed vs setup() (e.g. hot reload)
        if self._broker_parsed != parsed:
            log.info("MQTT broker URL changed — rebuilding client")
            self.disconnect()
            self._broker_parsed = parsed
            self.setup()

        host, port = parsed["host"], parsed["port"]
        log.info(f"Connecting to MQTT broker {host}:{port} ({parsed['transport']})...")
        self._client.connect_async(host, port=port, keepalive=60)
        self._client.loop_start()

    def disconnect(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    # ──────────────────────────────────────────────────────────────────────────
    # Topics
    # ──────────────────────────────────────────────────────────────────────────
    def _topic(self, suffix: str) -> str:
        return f"nocko/{self._tenant_id}/{self._agent_id}/{suffix}"

    # ──────────────────────────────────────────────────────────────────────────
    # Publish
    # ──────────────────────────────────────────────────────────────────────────
    def publish(self, topic_suffix: str, payload: dict, qos: int = 1) -> bool:
        """
        Publish a JSON payload to a data plane topic.
        Falls back to offline queue if not connected.
        """
        if not self._connected:
            log.debug(f"MQTT offline — queuing {topic_suffix}")
            q.enqueue(topic_suffix, payload)
            return False

        topic = self._topic(topic_suffix)
        msg = json.dumps(payload)
        result = self._client.publish(topic, msg, qos=qos)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            log.warning(f"MQTT publish failed rc={result.rc}, queuing")
            q.enqueue(topic_suffix, payload)
            return False
        return True

    def publish_heartbeat(self, queue_size: int = 0) -> None:
        """Send agent_presence heartbeat (QoS 0 — fire and forget)."""
        payload = {
            "schema_version": "1.0",
            "tenant_id": self._tenant_id,
            "agent_id": self._agent_id,
            "sent_at": int(time.time()),
            "payload_type": "heartbeat",
            "records": [{
                "clock": int(time.time()),
                "status": "ok",
                "queue_size": queue_size,
                "agent_version": kv_get("agent_version", "1.0.0"),
            }],
        }
        topic = self._topic("agent_presence")
        self._client.publish(topic, json.dumps(payload), qos=0)

    # ──────────────────────────────────────────────────────────────────────────
    # Replay offline queue
    # ──────────────────────────────────────────────────────────────────────────
    def flush_queue(self) -> int:
        """Attempt to send pending items from offline queue. Returns count sent."""
        if not self._connected:
            return 0
        items = q.get_pending(limit=50)
        sent = 0
        for item in items:
            try:
                payload = json.loads(item.payload)
                ok = self.publish(item.type, payload)
                if ok:
                    q.mark_sent(item.id)
                    sent += 1
                else:
                    q.mark_failed(item.id)
            except Exception as e:
                log.error(f"Queue flush error item={item.id}: {e}")
                q.mark_failed(item.id)
        if sent:
            log.info(f"Flushed {sent} queued items")
        return sent

    # ──────────────────────────────────────────────────────────────────────────
    # Register callbacks
    # ──────────────────────────────────────────────────────────────────────────
    def on_command(self, callback: CommandCallback) -> None:
        """Register handler for incoming portal commands."""
        self._command_callback = callback

    def on_config_signal(self, callback: Callable[[], None]) -> None:
        """Register handler for config change signal from portal."""
        self._config_signal_callback = callback

    # ──────────────────────────────────────────────────────────────────────────
    # Paho callbacks
    # ──────────────────────────────────────────────────────────────────────────
    def _on_connect(self, client, userdata, flags, rc, properties=None) -> None:
        if rc == 0:
            self._connected = True
            log.info("MQTT connected")
            # Subscribe to control plane
            client.subscribe(self._topic("commands"), qos=1)
            client.subscribe(self._topic("config"), qos=1)
            # Flush any offline queue
            self.flush_queue()
        else:
            log.error(f"MQTT connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc, properties=None) -> None:
        self._connected = False
        if rc != 0:
            log.warning(f"MQTT disconnected unexpectedly rc={rc}. paho will auto-reconnect.")

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            log.warning(f"MQTT message parse error topic={topic}")
            return

        if topic.endswith("/commands"):
            log.info(f"Received command: {payload.get('command_type')}")
            if self._command_callback:
                self._command_callback(payload)

        elif topic.endswith("/config"):
            log.info("Received config change signal from portal")
            if self._config_signal_callback:
                self._config_signal_callback()

    # ──────────────────────────────────────────────────────────────────────────
    # State
    # ──────────────────────────────────────────────────────────────────────────
    @property
    def connected(self) -> bool:
        return self._connected


# Singleton
mqtt_client = MQTTClient()
