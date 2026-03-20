"""MQTT control channel for Proxy Agent."""
from __future__ import annotations

import json
import ssl
import threading
import time
import uuid
from collections import deque
from typing import Callable


_seen_ids: deque[str] = deque(maxlen=200)
_seen_lock = threading.Lock()


def mark_seen(command_id: str) -> bool:
    with _seen_lock:
        if command_id in _seen_ids:
            return False
        _seen_ids.append(command_id)
        return True


class ProxyMqttClient:
    """Persistent MQTT client for NAT-friendly portal interaction."""

    def __init__(self, config: dict, run_sync_fn: Callable[[], dict], heartbeat_interval: int = 30):
        self._config = config
        self._run_sync = run_sync_fn
        self._heartbeat_interval = max(10, heartbeat_interval)
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._connected = threading.Event()

    def _agent_id(self) -> str:
        return str(self._config.get("agent_id", "") or "").strip()

    def _agent_token(self) -> str:
        return str(self._config.get("agent_token", "") or "").strip()

    def _portal_url(self) -> str:
        return str(self._config.get("portal_url", "") or "").strip().rstrip("/")

    def _agent_mac(self) -> str:
        configured = str(self._config.get("mac_address", "") or "").strip()
        if configured:
            return configured
        try:
            value = uuid.getnode()
        except Exception:
            return ""
        return ":".join(f"{(value >> shift) & 0xFF:02X}" for shift in range(40, -1, -8))

    def _broker_host(self) -> str:
        explicit = str(self._config.get("mqtt_host", "") or "").strip()
        if explicit:
            return explicit
        url = self._portal_url()
        for scheme in ("https://", "http://"):
            if url.startswith(scheme):
                url = url[len(scheme):]
        return url.split("/")[0]

    def _use_tls(self) -> bool:
        explicit = str(self._config.get("mqtt_host", "") or "").strip()
        if explicit:
            return bool(self._config.get("mqtt_tls", False))
        return self._portal_url().startswith("https://")

    def _mqtt_topic_base(self) -> str:
        return f"proxy/agents/{self._agent_id()}"

    def _heartbeat_payload(self) -> dict:
        return {
            "agent_id": self._agent_id(),
            "agent_token": self._agent_token(),
            "hostname": self._config.get("hostname", ""),
            "ip_address": self._config.get("ip_address", ""),
            "mac_address": self._agent_mac(),
            "portal_url": self._config.get("portal_url", ""),
            "version": self._config.get("version", "0.1.0"),
            "site_name": self._config.get("site_name", ""),
            "capabilities": self._config.get("collectors_enabled", ["snmp"]),
            "status": "online",
        }

    def _publish_json(self, client, topic: str, payload: dict) -> None:
        client.publish(topic, json.dumps(payload, ensure_ascii=False), qos=1)

    def _publish_heartbeat(self, client) -> None:
        self._publish_json(client, f"{self._mqtt_topic_base()}/heartbeat", self._heartbeat_payload())

    def _publish_result(self, client, command_id: str, status: str, result: dict | str) -> None:
        self._publish_json(
            client,
            f"{self._mqtt_topic_base()}/results",
            {
                "agent_id": self._agent_id(),
                "agent_token": self._agent_token(),
                "command_id": command_id,
                "status": status,
                "result": result,
            },
        )

    def start(self) -> None:
        if not self._agent_id() or not self._agent_token():
            print("MQTT disabled for Proxy Agent: missing agent_id or agent_token")
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name="proxy-mqtt")
        self._thread.start()
        print("Proxy Agent MQTT client started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)

    def _looks_like_tls_error(self, exc: Exception) -> bool:
        message = str(exc).lower()
        return any(token in message for token in ("ssl", "tls", "certificate", "verify", "hostname mismatch"))

    def _configure_tls(self, client, insecure: bool) -> None:
        cert_reqs = ssl.CERT_NONE if insecure else ssl.CERT_REQUIRED
        client.tls_set(cert_reqs=cert_reqs)
        client.tls_insecure_set(insecure)

    def _run(self) -> None:
        try:
            import paho.mqtt.client as mqtt  # type: ignore
        except ImportError:
            print("paho-mqtt is not installed; Proxy Agent MQTT disabled")
            return

        host = self._broker_host()
        port = int(self._config.get("mqtt_port", 443))
        transport = str(self._config.get("mqtt_transport", "websockets"))
        ws_path = str(self._config.get("mqtt_path", "/mqtt"))
        use_tls = bool(self._config.get("mqtt_tls", self._use_tls()))
        verify_tls = bool(self._config.get("mqtt_tls_verify", True))
        allow_insecure_fallback = bool(self._config.get("mqtt_tls_allow_insecure_fallback", False))
        topic = f"{self._mqtt_topic_base()}/commands"
        backoff = 5
        insecure_tls_active = use_tls and not verify_tls

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                client.subscribe(topic, qos=1)
                self._connected.set()
                self._publish_heartbeat(client)
            else:
                self._connected.clear()
                print(f"Proxy Agent MQTT connect failed rc={rc}")

        def on_disconnect(client, userdata, rc):
            self._connected.clear()

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
                if not isinstance(payload, dict):
                    return
                command_id = str(payload.get("id", "") or "")
                command_type = str(payload.get("type", "") or "")
                command_payload = payload.get("payload", {})
                if command_id and not mark_seen(command_id):
                    return

                if command_type == "ping":
                    self._publish_result(client, command_id, "acked", {"message": "pong"})
                    return

                if command_type == "sync_now":
                    try:
                        result = self._run_sync()
                        self._publish_result(client, command_id, "acked", result)
                    except Exception as exc:
                        self._publish_result(client, command_id, "failed", {"error": str(exc)})
                    return

                self._publish_result(
                    client,
                    command_id,
                    "failed",
                    {"error": f"Unsupported Proxy Agent command: {command_type}", "payload": command_payload},
                )
            except Exception as exc:
                print(f"Proxy Agent MQTT message error: {exc}")

        while not self._stop.is_set():
            client = mqtt.Client(
                client_id=f"proxy-agent-{self._agent_id()}",
                clean_session=False,
                transport=transport,
            )
            if transport == "websockets":
                client.ws_set_options(path=ws_path)
            if use_tls:
                self._configure_tls(client, insecure=insecure_tls_active)
            client.on_connect = on_connect
            client.on_disconnect = on_disconnect
            client.on_message = on_message
            client.reconnect_delay_set(min_delay=1, max_delay=30)
            try:
                client.connect(host, port, keepalive=60)
                client.loop_start()
                backoff = 5

                last_heartbeat = 0.0
                while not self._stop.is_set():
                    if self._connected.is_set() and (time.time() - last_heartbeat) >= self._heartbeat_interval:
                        self._publish_heartbeat(client)
                        last_heartbeat = time.time()
                    time.sleep(1)

                client.loop_stop()
                client.disconnect()
                break
            except Exception as exc:
                if use_tls and not insecure_tls_active and allow_insecure_fallback and self._looks_like_tls_error(exc):
                    insecure_tls_active = True
                    print(f"Proxy Agent MQTT TLS verify failed, falling back to insecure TLS: {exc}")
                    continue
                print(f"Proxy Agent MQTT connect error ({exc}). Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff = min(backoff * 2, 120)
