"""MQTT publisher — singleton async client for the FastAPI backend.

Usage:
    from mqtt_publisher import publish_command, MqttPublisher

    # In lifespan startup:
    await MqttPublisher.connect()

    # Publishing a command:
    await publish_command(device_id, {"id": cmd_id, "type": "rename_computer", "payload": {...}})
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

log = logging.getLogger("mqtt")

_MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
_MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

_client: Any = None  # aiomqtt.Client instance
_lock = asyncio.Lock()


async def publish_command(device_id: str, command: dict) -> None:
    """Publish a command to the device's MQTT topic (QoS 1).

    Silently skips if MQTT is not connected — HTTP polling is the fallback.
    """
    global _client
    if _client is None:
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
        global _client
        import aiomqtt  # deferred so startup doesn't fail if not installed

        backoff = 2
        while True:
            try:
                async with aiomqtt.Client(
                    hostname=_MQTT_HOST,
                    port=_MQTT_PORT,
                    identifier="nocko-mdm-backend",
                    keepalive=60,
                ) as client:
                    _client = client
                    backoff = 2  # reset on success
                    log.info("MQTT publisher connected to %s:%s", _MQTT_HOST, _MQTT_PORT)
                    # Keep the connection alive indefinitely
                    await asyncio.Event().wait()
            except Exception as exc:
                _client = None
                log.warning("MQTT connection lost (%s). Retrying in %ss…", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
