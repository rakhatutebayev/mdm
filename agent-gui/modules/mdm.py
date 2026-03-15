from __future__ import annotations

import logging
from typing import Any

import requests

from config import AgentConfig
from device_info import collect_checkin_payload, collect_enrollment_payload


class MdmAgentClient:
    def __init__(self, config: AgentConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"NOCKO-Agent/{config.agent_version}"})

    @property
    def api_base(self) -> str:
        return self.config.server_url.rstrip("/") + "/api/v1/mdm/windows"

    def enroll_if_needed(self) -> str:
        if self.config.device_id:
            return self.config.device_id

        if not self.config.customer_id or not self.config.enrollment_token:
            raise RuntimeError("customer_id and enrollment_token are required before enrollment")

        payload = collect_enrollment_payload(self.config)
        self.logger.info("Enrolling device with %s", self.api_base)
        response = self.session.post(
            f"{self.api_base}/enroll",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.config.device_id = data["device_id"]
        self.config.save()
        self.logger.info("Enrollment complete. device_id=%s", self.config.device_id)
        return self.config.device_id

    def checkin(self) -> dict[str, Any]:
        self.enroll_if_needed()
        payload = collect_checkin_payload(self.config)
        response = self.session.post(
            f"{self.api_base}/checkin",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.logger.info("Check-in OK for device_id=%s", self.config.device_id)
        return data

    def fetch_commands(self) -> list[dict[str, Any]]:
        self.enroll_if_needed()
        response = self.session.get(
            f"{self.api_base}/commands",
            params={"device_id": self.config.device_id},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("commands", [])

    def run_once(self) -> None:
        self.checkin()
        commands = self.fetch_commands()
        if commands:
            self.logger.warning("Command execution is not implemented yet: %s", commands)

    def decommission(self, reason: str = "Agent removed") -> None:
        if not self.config.device_id:
            return
        response = self.session.post(
            f"{self.api_base}/decommission",
            json={"device_id": self.config.device_id, "reason": reason},
            timeout=30,
        )
        response.raise_for_status()
        self.logger.info("Device decommissioned: %s", self.config.device_id)
