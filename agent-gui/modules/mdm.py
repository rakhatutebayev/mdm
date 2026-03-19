from __future__ import annotations

import logging
from typing import Any

import requests
import urllib3

from config import AgentConfig
from device_info import (
    collect_enrollment_payload,
    collect_heartbeat_payload,
    collect_inventory_payload,
    collect_metrics_payload,
)

class MdmAgentClient:
    def __init__(self, config: AgentConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.session = requests.Session()
        self._tls_verify = bool(getattr(config, "tls_verify", True))
        self._tls_fallback_allowed = bool(getattr(config, "tls_allow_insecure_fallback", False))
        self.session.verify = self._tls_verify
        self.session.headers.update({"User-Agent": f"NOCKO-Agent/{config.agent_version}"})

    def _enable_insecure_tls_fallback(self, reason: Exception) -> None:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.session.verify = False
        self._tls_verify = False
        self.logger.warning(
            "TLS certificate verification failed for %s. Falling back to insecure HTTPS because tls_allow_insecure_fallback=true: %s",
            self.config.server_url,
            reason,
        )

    def _request(self, method: str, url: str, **kwargs):
        try:
            return self.session.request(method, url, **kwargs)
        except requests.exceptions.SSLError as exc:
            if not self._tls_verify or not self._tls_fallback_allowed:
                raise
            self._enable_insecure_tls_fallback(exc)
            return self.session.request(method, url, **kwargs)

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
        response = self._request(
            "POST",
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

    def heartbeat(self) -> dict[str, Any]:
        self.enroll_if_needed()
        payload = collect_heartbeat_payload(self.config)
        response = self._request(
            "POST",
            f"{self.api_base}/checkin",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.logger.info("Heartbeat OK for device_id=%s", self.config.device_id)
        return data

    def send_metrics(self) -> dict[str, Any]:
        self.enroll_if_needed()
        payload = collect_metrics_payload(self.config)
        response = self._request(
            "POST",
            f"{self.api_base}/checkin",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.logger.info("Metrics upload OK for device_id=%s", self.config.device_id)
        return data

    def send_inventory(self) -> dict[str, Any]:
        self.enroll_if_needed()
        payload = collect_inventory_payload(self.config)
        response = self._request(
            "POST",
            f"{self.api_base}/inventory",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        self.logger.info("Inventory upload OK for device_id=%s", self.config.device_id)
        return data

    def fetch_commands(self) -> list[dict[str, Any]]:
        self.enroll_if_needed()
        response = self._request(
            "GET",
            f"{self.api_base}/commands",
            params={"device_id": self.config.device_id},
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("commands", [])

    def decommission(self, reason: str = "Agent removed") -> None:
        if not self.config.device_id:
            return
        response = self._request(
            "POST",
            f"{self.api_base}/decommission",
            json={"device_id": self.config.device_id, "reason": reason},
            timeout=30,
        )
        response.raise_for_status()
        self.logger.info("Device decommissioned: %s", self.config.device_id)

    def ack_command(self, command_id: str, status: str = "acked", result: str | None = None) -> None:
        """Acknowledge a command result back to the server."""
        self._request(
            "POST",
            f"{self.api_base}/commands/ack",
            json={"command_id": command_id, "status": status, "result": result},
            timeout=15,
        )
