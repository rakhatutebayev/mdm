"""
NOCKO Agent — Backup Module (Stub)
Placeholder implementation. Full file-sync backup engine planned for v2.
"""
import threading
from logger import get_logger

log = get_logger("backup")


class BackupModule:
    def __init__(self, on_status_change=None):
        self.on_status_change = on_status_change
        self.enabled   = False
        self.last_run  = None
        self.status    = "Not configured"

    def start(self):
        log.info("Backup module: stub — not yet implemented")
        self._notify("Coming soon")

    def stop(self):
        pass

    def run_now(self):
        log.info("Backup: manual run requested (stub)")
        self._notify("Coming soon")

    def _notify(self, status: str):
        self.status = status
        if self.on_status_change:
            try:
                self.on_status_change(status)
            except Exception:
                pass
