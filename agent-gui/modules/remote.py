"""
NOCKO Agent — Remote Access Module (Stub)
Placeholder implementation. Full AnyDesk-like remote access planned for v2.
"""
from logger import get_logger

log = get_logger("remote")


class RemoteModule:
    def __init__(self, on_status_change=None):
        self.on_status_change = on_status_change
        self.enabled   = False
        self.session_id = None
        self.status    = "Not configured"

    def start(self):
        log.info("Remote module: stub — not yet implemented")
        self._notify("Coming soon")

    def stop(self):
        pass

    def enable(self):
        log.info("Remote: enable requested (stub)")
        self._notify("Coming soon")

    def _notify(self, status: str):
        self.status = status
        if self.on_status_change:
            try:
                self.on_status_change(status)
            except Exception:
                pass
