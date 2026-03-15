from __future__ import annotations

import logging
import threading
import time

from config import AgentConfig
from modules.mdm import MdmAgentClient


def run_agent_loop(
    config: AgentConfig,
    logger: logging.Logger,
    stop_event: threading.Event,
) -> None:
    client = MdmAgentClient(config, logger)
    logger.info("Agent loop started with check-in interval=%ss", config.checkin_interval)

    while not stop_event.is_set():
        try:
            client.run_once()
        except Exception as exc:
            logger.exception("Agent cycle failed: %s", exc)
        stop_event.wait(max(30, int(config.checkin_interval)))

    logger.info("Agent loop stopped")
