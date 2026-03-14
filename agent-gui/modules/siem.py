"""
NOCKO Agent — SIEM Module
Collects Windows Security/System/Application events and forwards
them to the NOCKO backend. Uses an in-memory buffer with periodic flush.
Falls back gracefully on non-Windows.
"""
import platform
import threading
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from config import config
from logger import get_logger

log = get_logger("siem")

IS_WINDOWS = platform.system() == "Windows"

# Event IDs we care about (Security log)
SECURITY_EVENT_IDS = {
    4624: "Logon Success",
    4625: "Logon Failure",
    4634: "Logoff",
    4648: "Explicit Credential Logon",
    4672: "Special Privileges Assigned",
    4688: "New Process Created",
    4698: "Scheduled Task Created",
    4702: "Scheduled Task Updated",
    4720: "User Account Created",
    4726: "User Account Deleted",
    4732: "Member Added to Security Group",
    4740: "Account Lockout",
    4756: "Member Added to Universal Group",
}

SYSTEM_EVENT_IDS = {
    7036: "Service State Change",
    7045: "New Service Installed",
}


def _collect_events_windows(log_name: str, event_ids: dict, max_events: int = 50) -> list[dict]:
    """Read recent events from a Windows Event Log channel."""
    events = []
    try:
        import win32evtlog      # type: ignore
        import win32evtlogutil  # type: ignore
        import win32con         # type: ignore

        handle = win32evtlog.OpenEventLog(None, log_name)
        flags  = win32evtlog.EVENTLOG_BACKWARDS_READ | win32evtlog.EVENTLOG_SEQUENTIAL_READ

        while True:
            records = win32evtlog.ReadEventLog(handle, flags, 0)
            if not records:
                break
            for rec in records:
                if rec.EventID & 0xFFFF in event_ids:
                    try:
                        msg = win32evtlogutil.SafeFormatMessage(rec, log_name)
                    except Exception:
                        msg = str(rec.StringInserts)

                    events.append({
                        "event_id":    rec.EventID & 0xFFFF,
                        "event_name":  event_ids.get(rec.EventID & 0xFFFF, "Unknown"),
                        "source":      rec.SourceName,
                        "log":         log_name,
                        "time":        rec.TimeGenerated.Format(),
                        "message":     (msg or "")[:500],
                        "hostname":    rec.ComputerName,
                    })
                    if len(events) >= max_events:
                        break
            if len(events) >= max_events:
                break
        win32evtlog.CloseEventLog(handle)
    except Exception as e:
        log.warning(f"Error reading {log_name} events: {e}")
    return events


def _generate_demo_events() -> list[dict]:
    """Generate fake events for macOS/Linux dev."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    return [
        {
            "event_id":   4624,
            "event_name": "Logon Success",
            "source":     "Microsoft-Windows-Security-Auditing",
            "log":        "Security",
            "time":       ts,
            "message":    "An account was successfully logged on. Account: DEV\\Rakhat",
            "hostname":   platform.node(),
        },
        {
            "event_id":   7036,
            "event_name": "Service State Change",
            "source":     "Service Control Manager",
            "log":        "System",
            "time":       ts,
            "message":    "The NOCKO Agent service entered the running state.",
            "hostname":   platform.node(),
        },
    ]


class SIEMModule:
    """Collects Windows events and sends them to NOCKO backend."""

    def __init__(self, on_event=None):
        self._thread: Optional[threading.Thread] = None
        self._stop   = threading.Event()
        self.on_event = on_event   # callback(event: dict)
        self.event_buffer: list[dict] = []
        self.events_sent: int = 0

    def start(self):
        if not config.siem_enabled:
            log.info("SIEM module disabled in config, skipping")
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="siem-loop")
        self._thread.start()
        log.info("SIEM module started")

    def stop(self):
        self._stop.set()
        log.info("SIEM module stopped")

    def collect_now(self):
        threading.Thread(target=self._collect_and_send, daemon=True).start()

    def _loop(self):
        while not self._stop.is_set():
            self._collect_and_send()
            self._stop.wait(timeout=config.siem_interval * 60)

    def _collect_and_send(self):
        events = self._collect()
        if not events:
            return
        for ev in events:
            self.event_buffer.append(ev)
            if self.on_event:
                try:
                    self.on_event(ev)
                except Exception:
                    pass

        # Keep buffer limited to last 500
        self.event_buffer = self.event_buffer[-500:]
        self._send(events)

    def _collect(self) -> list[dict]:
        if IS_WINDOWS:
            sec  = _collect_events_windows("Security", SECURITY_EVENT_IDS)
            sys_ = _collect_events_windows("System",   SYSTEM_EVENT_IDS)
            return sec + sys_
        else:
            return _generate_demo_events()

    def _send(self, events: list[dict]):
        if not config.enrollment_token:
            log.debug("SIEM: no enrollment token, skipping send")
            return
        try:
            resp = requests.post(
                f"{config.mdm_server}/siem/events",
                json={
                    "device_token": config.enrollment_token,
                    "events":       events,
                },
                timeout=15,
            )
            if resp.status_code in (200, 201, 202):
                self.events_sent += len(events)
                log.info(f"SIEM: sent {len(events)} events (total: {self.events_sent})")
            else:
                log.warning(f"SIEM: server returned {resp.status_code}")
        except Exception as e:
            log.warning(f"SIEM send failed: {e}")

    @property
    def recent_events(self) -> list[dict]:
        return list(self.event_buffer[-100:])
