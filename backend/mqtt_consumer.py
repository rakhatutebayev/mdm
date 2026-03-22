"""
MQTT Ingest Consumer for NOCKO Portal Backend.

Subscribes to agent data-plane topics and routes to the ingest endpoint logic.
Runs as a background task on portal startup.

Topics subscribed:
  nocko/+/+/metrics.fast
  nocko/+/+/metrics.slow
  nocko/+/+/inventory
  nocko/+/+/events
  nocko/+/+/agent_presence     ← heartbeat

Auth: MQTT broker validates client certificates.
The consumer forwards messages to the same ingest logic used by the REST API.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Optional

import paho.mqtt.client as mqtt
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

log = logging.getLogger("nocko.mqtt_consumer")


class MQTTIngestConsumer:
    """
    Subscribes to agent data-plane topics and calls ingest logic.
    Runs alongside FastAPI via asyncio background task.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sf = session_factory
        self._client: Optional[mqtt.Client] = None
        self._connected = False

    def start(self) -> None:
        """Start MQTT consumer in paho background thread."""
        broker = os.getenv("MQTT_BROKER_HOST", "localhost")
        port = int(os.getenv("MQTT_BROKER_PORT", 1883))

        self._client = mqtt.Client(client_id="nocko-portal-consumer", protocol=mqtt.MQTTv5)
        self._client.on_connect = self._on_connect
        self._client.on_message = self._on_message
        self._client.on_disconnect = self._on_disconnect

        # mTLS (optional, enable in production)
        ca_cert = os.getenv("MQTT_CA_CERT")
        if ca_cert and os.path.exists(ca_cert):
            import ssl
            ctx = ssl.create_default_context(cafile=ca_cert)
            self._client.tls_set_context(ctx)

        self._client.connect_async(broker, port=port, keepalive=60)
        self._client.loop_start()
        log.info(f"MQTT consumer connecting to {broker}:{port}")

    def stop(self) -> None:
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()

    def _on_connect(self, client, userdata, flags, rc, props=None) -> None:
        if rc == 0:
            self._connected = True
            # Subscribe to all agent data plane topics
            client.subscribe("nocko/+/+/metrics.fast", qos=1)
            client.subscribe("nocko/+/+/metrics.slow", qos=1)
            client.subscribe("nocko/+/+/inventory", qos=1)
            client.subscribe("nocko/+/+/events", qos=1)
            client.subscribe("nocko/+/+/agent_presence", qos=0)
            log.info("MQTT consumer subscribed to agent topics")
        else:
            log.error(f"MQTT consumer connect failed rc={rc}")

    def _on_disconnect(self, client, userdata, rc, props=None) -> None:
        self._connected = False
        if rc != 0:
            log.warning(f"MQTT consumer disconnected rc={rc}, will reconnect")

    def _on_message(self, client, userdata, msg: mqtt.MQTTMessage) -> None:
        """Dispatch incoming MQTT message to async ingest logic."""
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except Exception:
            log.warning(f"MQTT parse error topic={msg.topic}")
            return

        # Determine payload_type from topic suffix if not in payload
        topic_parts = msg.topic.split("/")
        topic_suffix = topic_parts[-1] if topic_parts else ""
        if "payload_type" not in payload:
            payload["payload_type"] = topic_suffix

        # We cannot await here (paho callback thread) — schedule as asyncio task
        asyncio.create_task(self._dispatch(payload))

    async def _dispatch(self, payload: dict) -> None:
        """Run ingest logic in async DB session."""
        from routers.agent_ingest import process_envelope
        try:
            async with self._sf() as session:
                await process_envelope(payload, session)
                await session.commit()
        except Exception as e:
            log.error(f"MQTT ingest error: {e}", exc_info=True)


# Singleton
_consumer: Optional[MQTTIngestConsumer] = None


def get_consumer(session_factory: async_sessionmaker) -> MQTTIngestConsumer:
    global _consumer
    if _consumer is None:
        _consumer = MQTTIngestConsumer(session_factory)
    return _consumer
