"""MQTT publisher — singleton async client for the FastAPI backend.

Gracefully degrades if aiomqtt is not installed or EMQX is unreachable.
In that case, commands are still persisted in DB and delivered via HTTP polling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger("mqtt")

_MQTT_HOST      = os.getenv("MQTT_HOST",      "localhost")
_MQTT_PORT      = int(os.getenv("MQTT_PORT",  "8083"))
_MQTT_TRANSPORT = os.getenv("MQTT_TRANSPORT", "websockets")  # 'websockets' or 'tcp'
_MQTT_PATH      = os.getenv("MQTT_PATH",      "/mqtt")       # WebSocket endpoint path
_MQTT_AVAILABLE = False  # set True once aiomqtt import succeeds

_client: Any = None
_lock = asyncio.Lock()


async def publish_command(device_id: str, command: dict) -> None:
    """Publish a command to the device's MQTT topic (QoS 1).

    Silently skips if MQTT is not connected — HTTP polling is the fallback.
    """
    if not _MQTT_AVAILABLE or _client is None:
        return
    topic = f"mdm/devices/{device_id}/commands"
    try:
        await _client.publish(topic, json.dumps(command), qos=1)
        log.debug("MQTT published to %s: %s", topic, command.get("type"))
    except Exception as exc:
        log.warning("MQTT publish failed (non-fatal): %s", exc)


class MqttPublisher:
    """Manages the aiomqtt client lifecycle."""

    _task: asyncio.Task | None = None

    @classmethod
    async def connect(cls) -> None:
        """Start background task that maintains the MQTT connection."""
        cls._task = asyncio.create_task(cls._run())
        log.info("MQTT publisher task started → %s:%s", _MQTT_HOST, _MQTT_PORT)

    @classmethod
    async def disconnect(cls) -> None:
        if cls._task:
            cls._task.cancel()
            try:
                await cls._task
            except asyncio.CancelledError:
                pass

    @classmethod
    async def _run(cls) -> None:
        global _client, _MQTT_AVAILABLE

        try:
            import aiomqtt  # noqa: F401  — check availability
            _MQTT_AVAILABLE = True
        except ImportError:
            log.warning("aiomqtt not installed — MQTT publisher disabled. HTTP polling only.")
            return

        import aiomqtt  # type: ignore

        backoff = 2
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=_MQTT_HOST,
                    port=_MQTT_PORT,
                    identifier="nocko-mdm-backend",
                    keepalive=60,
                    websocket_path=_MQTT_PATH if _MQTT_TRANSPORT == "websockets" else None,
                ) as client:
                    _client = client
                    backoff = 2
                    log.info(
                        "MQTT publisher connected → %s:%s (transport=%s)",
                        _MQTT_HOST, _MQTT_PORT, _MQTT_TRANSPORT,
                    )
                    await asyncio.Event().wait()
            except asyncio.CancelledError:
                _client = None
                break
            except Exception as exc:
                _client = None
                log.warning("MQTT connection lost (%s). Retrying in %ss…", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
