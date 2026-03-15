from __future__ import annotations

import logging
import random
import threading
import time

from config import AgentConfig
from modules.mdm import MdmAgentClient


def _next_due(now: float, interval: int) -> float:
    # Small jitter prevents many agents from hammering the server at the same second.
    return now + max(5, interval) + random.uniform(0, min(5, interval * 0.1))


def run_agent_loop(
    config: AgentConfig,
    logger: logging.Logger,
    stop_event: threading.Event,
) -> None:
    client = MdmAgentClient(config, logger)
    logger.info(
        "Agent loop started heartbeat=%ss metrics=%ss inventory=%ss commands=%ss",
        config.heartbeat_interval,
        config.metrics_interval,
        config.inventory_interval,
        config.commands_interval,
    )

    client.enroll_if_needed()
    now = time.monotonic()
    next_heartbeat = now
    next_metrics = now
    next_inventory = now
    next_commands = now

    while not stop_event.is_set():
        now = time.monotonic()

        if now >= next_heartbeat:
            try:
                client.heartbeat()
            except Exception as exc:
                logger.exception("Heartbeat failed: %s", exc)
            next_heartbeat = _next_due(now, int(config.heartbeat_interval))

        if now >= next_metrics:
            try:
                client.send_metrics()
            except Exception as exc:
                logger.exception("Metrics upload failed: %s", exc)
            next_metrics = _next_due(now, int(config.metrics_interval))

        if now >= next_inventory:
            try:
                client.send_inventory()
            except Exception as exc:
                logger.exception("Inventory upload failed: %s", exc)
            next_inventory = _next_due(now, int(config.inventory_interval))

        if now >= next_commands:
            try:
                commands = client.fetch_commands()
                if commands:
                    logger.warning("Command execution is not implemented yet: %s", commands)
            except Exception as exc:
                logger.exception("Command polling failed: %s", exc)
            next_commands = _next_due(now, int(config.commands_interval))

        wait_for = max(
            1.0,
            min(next_heartbeat, next_metrics, next_inventory, next_commands) - time.monotonic(),
        )
        stop_event.wait(wait_for)

    logger.info("Agent loop stopped")
