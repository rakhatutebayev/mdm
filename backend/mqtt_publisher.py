"""MQTT control plane for the FastAPI backend.

Publishes commands to devices/agents and subscribes to Proxy Agent heartbeat
and result topics so NATed agents can stay online through outbound MQTT.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Any

from sqlalchemy import select

from database import AsyncSessionLocal
from models import ProxyAgent, ProxyAgentCommand

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


async def publish_proxy_command(agent_id: str, command: dict) -> None:
    """Publish a real-time command to a Proxy Agent."""
    if not _MQTT_AVAILABLE or _client is None:
        return
    topic = f"proxy/agents/{agent_id}/commands"
    try:
        await _client.publish(topic, json.dumps(command), qos=1)
        log.debug("MQTT published proxy command to %s: %s", topic, command.get("type"))
    except Exception as exc:
        log.warning("Proxy MQTT publish failed (non-fatal): %s", exc)


def _topic_to_str(topic: Any) -> str:
    if hasattr(topic, "value"):
        return str(topic.value)
    return str(topic)


def _extract_proxy_agent_id(topic: str) -> str:
    parts = topic.split("/")
    if len(parts) >= 4 and parts[0] == "proxy" and parts[1] == "agents":
        return parts[2]
    return ""


def _serialize_result(payload: dict[str, Any]) -> str:
    result = payload.get("result")
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    try:
        return json.dumps(result, ensure_ascii=False)
    except Exception:
        return str(result)


async def _handle_proxy_heartbeat(payload: dict[str, Any], topic: str) -> None:
    agent_id = _extract_proxy_agent_id(topic)
    agent_token = str(payload.get("agent_token", "") or "").strip()
    if not agent_id or not agent_token:
        return

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ProxyAgent).where(
                ProxyAgent.id == agent_id,
                ProxyAgent.auth_token == agent_token,
            )
        )
        agent = result.scalar_one_or_none()
        if not agent:
            return

        agent.hostname = str(payload.get("hostname", "") or agent.hostname)
        agent.ip_address = str(payload.get("ip_address", "") or agent.ip_address)
        agent.mac_address = str(payload.get("mac_address", "") or agent.mac_address)
        agent.portal_url = str(payload.get("portal_url", "") or agent.portal_url)
        agent.version = str(payload.get("version", "") or agent.version)
        agent.site_name = str(payload.get("site_name", "") or agent.site_name)
        capabilities = payload.get("capabilities", [])
        if isinstance(capabilities, list):
            caps = ", ".join(str(item).strip() for item in capabilities if str(item).strip())
            if caps:
                agent.capabilities = caps
        agent.status = "online" if agent.is_registered else "not_registered"
        agent.last_checkin = datetime.utcnow()
        await db.commit()


async def _handle_proxy_result(payload: dict[str, Any], topic: str) -> None:
    agent_id = _extract_proxy_agent_id(topic)
    agent_token = str(payload.get("agent_token", "") or "").strip()
    command_id = str(payload.get("command_id", "") or "").strip()
    if not agent_id or not agent_token or not command_id:
        return

    async with AsyncSessionLocal() as db:
        agent_result = await db.execute(
            select(ProxyAgent).where(
                ProxyAgent.id == agent_id,
                ProxyAgent.auth_token == agent_token,
            )
        )
        agent = agent_result.scalar_one_or_none()
        if not agent:
            return

        command_result = await db.execute(
            select(ProxyAgentCommand).where(
                ProxyAgentCommand.id == command_id,
                ProxyAgentCommand.proxy_agent_id == agent_id,
            )
        )
        command = command_result.scalar_one_or_none()
        if not command:
            return

        status = str(payload.get("status", "") or "").strip() or "acked"
        command.status = status
        command.result = _serialize_result(payload)
        if status in {"acked", "completed", "failed"}:
            command.acked_at = datetime.utcnow()

        agent.status = "online" if agent.is_registered else "not_registered"
        agent.last_checkin = datetime.utcnow()
        await db.commit()


async def _handle_proxy_message(topic: str, payload: dict[str, Any]) -> None:
    if topic.endswith("/heartbeat"):
        await _handle_proxy_heartbeat(payload, topic)
        return
    if topic.endswith("/results"):
        await _handle_proxy_result(payload, topic)
        return


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
                        "MQTT control plane connected → %s:%s (transport=%s)",
                        _MQTT_HOST, _MQTT_PORT, _MQTT_TRANSPORT,
                    )
                    await client.subscribe("proxy/agents/+/heartbeat", qos=1)
                    await client.subscribe("proxy/agents/+/results", qos=1)
                    async for message in client.messages:
                        try:
                            topic = _topic_to_str(message.topic)
                            payload = json.loads(message.payload.decode("utf-8"))
                            if isinstance(payload, dict):
                                await _handle_proxy_message(topic, payload)
                        except Exception as exc:
                            log.warning("MQTT proxy message handling failed: %s", exc)
            except asyncio.CancelledError:
                _client = None
                break
            except Exception as exc:
                _client = None
                log.warning("MQTT connection lost (%s). Retrying in %ss…", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)
