"""
Watcher / Self-healing daemon for NOCKO Proxy Agent.

Monitors main.py process and restarts it if it crashes.
Respects a backoff strategy to avoid rapid restart loops.

Usage: python watcher.py
  (Normally called by the systemd service unit, not directly.)
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

_AGENT_SCRIPT = Path(__file__).parent / "main.py"
_MAX_RESTARTS = 10
_BACKOFF = [5, 10, 30, 60, 120]   # seconds between restart attempts


def run() -> None:
    restart_count = 0
    print(f"[watcher] Starting NOCKO Agent: {_AGENT_SCRIPT}", flush=True)

    while restart_count <= _MAX_RESTARTS:
        start_ts = time.time()
        proc = subprocess.run([sys.executable, str(_AGENT_SCRIPT)] + sys.argv[1:])

        uptime = time.time() - start_ts

        if uptime > 300:
            # Process ran >5 minutes — reset backoff counter
            restart_count = 0

        if proc.returncode == 0:
            print("[watcher] Agent exited cleanly. Stopping watcher.", flush=True)
            break

        restart_count += 1
        delay = _BACKOFF[min(restart_count - 1, len(_BACKOFF) - 1)]
        print(
            f"[watcher] Agent crashed (rc={proc.returncode}). "
            f"Restart #{restart_count}/{_MAX_RESTARTS} in {delay}s...",
            flush=True,
        )
        time.sleep(delay)
    else:
        print(f"[watcher] Max restarts ({_MAX_RESTARTS}) reached. Giving up.", flush=True)
        sys.exit(1)


if __name__ == "__main__":
    run()
