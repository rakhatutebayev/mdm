"""Structured logger for NOCKO Proxy Agent."""
import logging
import sys
from pathlib import Path
from typing import Optional


def setup_logger(name: str = "nocko-agent", level: str = "INFO", log_file: Optional[str] = None) -> logging.Logger:

    fmt = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))
    logger.handlers.clear()

    # Console handler
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # File handler (optional)
    if log_file:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(log_file, encoding="utf-8")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


# Module-level default logger — callers can use `from core.logger import log`
log = setup_logger()
