"""
NOCKO Agent — Structured Logger
Writes JSON logs to %ProgramData%/NOCKO-Agent/agent.log with rotation.
Also emits a Qt signal so the UI can display live logs.
"""
import logging
import os
import platform
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Callable, Optional

_callbacks: list[Callable[[str, str, str], None]] = []  # (level, module, msg)


def _log_dir() -> Path:
    if platform.system() == "Windows":
        base = Path(os.environ.get("ProgramData", "C:/ProgramData"))
        return base / "NOCKO-Agent"
    return Path.home() / ".nocko-agent"


def setup_logging(level: str = "INFO"):
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "agent.log"

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Rotating file handler (5 MB × 3 backups)
    fh = RotatingFileHandler(log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler (for dev)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    root.addHandler(ch)

    # Custom handler to push to UI callbacks
    class CallbackHandler(logging.Handler):
        def emit(self, record):
            level = record.levelname
            module = record.name
            msg = self.format(record)
            for cb in _callbacks:
                try:
                    cb(level, module, msg)
                except Exception:
                    pass

    cb_handler = CallbackHandler()
    cb_handler.setFormatter(fmt)
    root.addHandler(cb_handler)


def add_log_callback(cb: Callable[[str, str, str], None]):
    """Register a callback to receive (level, module, message) tuples."""
    _callbacks.append(cb)


def remove_log_callback(cb: Callable[[str, str, str], None]):
    if cb in _callbacks:
        _callbacks.remove(cb)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
