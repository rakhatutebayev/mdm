"""PTY terminal over WebSocket.

Connects to the backend WebSocket relay and spawns a PTY bash session
when requested. Works on Linux/macOS (uses pty module). On Windows it
falls back to a plain subprocess pipe (no full PTY support).

Protocol (JSON text frames):
  Backend → Agent:
    {"type": "open_pty", "cols": 220, "rows": 50}
    {"type": "close_pty"}
    {"type": "resize", "cols": N, "rows": M}
  Agent → Backend (output):
    raw bytes (PTY output) or {"type": "error", "message": "..."}
  Backend → Agent (input from browser):
    {"type": "input", "data": "<base64>"}  OR raw bytes
"""
from __future__ import annotations

import base64
import json
import logging
import os
import platform
import threading
import time
import select

logger = logging.getLogger(__name__)

_IS_WINDOWS = platform.system() == "Windows"


class PtySession:
    """Manages a single PTY subprocess session."""

    def __init__(self, send_output, cols: int = 220, rows: int = 50):
        self._send = send_output  # callable(bytes)
        self._cols = cols
        self._rows = rows
        self._fd: int | None = None
        self._pid: int | None = None
        self._thread: threading.Thread | None = None
        self._running = False

    def start(self):
        if _IS_WINDOWS:
            self._start_windows()
        else:
            self._start_unix()

    def _start_unix(self):
        import pty
        import struct
        import fcntl
        import termios

        shell = os.environ.get("SHELL", "/bin/bash")
        env = os.environ.copy()
        env["TERM"] = "xterm-256color"

        self._pid, self._fd = pty.fork()
        if self._pid == 0:
            # Child process
            os.execve(shell, [shell, "-l"], env)
            os._exit(1)

        # Set initial terminal size
        try:
            winsize = struct.pack("HHHH", self._rows, self._cols, 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

        self._running = True
        self._thread = threading.Thread(target=self._read_loop_unix, daemon=True)
        self._thread.start()

    def _read_loop_unix(self):
        import os
        while self._running and self._fd is not None:
            try:
                r, _, _ = select.select([self._fd], [], [], 0.1)
                if r:
                    data = os.read(self._fd, 4096)
                    if not data:
                        break
                    self._send(data)
            except OSError:
                break
        self._running = False

    def _start_windows(self):
        import subprocess
        self._proc = subprocess.Popen(
            ["cmd.exe"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        self._running = True
        self._thread = threading.Thread(target=self._read_loop_windows, daemon=True)
        self._thread.start()

    def _read_loop_windows(self):
        while self._running:
            try:
                data = self._proc.stdout.read(4096)
                if not data:
                    break
                self._send(data)
            except Exception:
                break
        self._running = False

    def write(self, data: bytes):
        if not self._running:
            return
        try:
            if _IS_WINDOWS:
                self._proc.stdin.write(data)
                self._proc.stdin.flush()
            else:
                os.write(self._fd, data)
        except Exception as e:
            logger.warning("PTY write error: %s", e)

    def resize(self, cols: int, rows: int):
        if _IS_WINDOWS or self._fd is None:
            return
        try:
            import struct
            import fcntl
            import termios
            winsize = struct.pack("HHHH", rows, cols, 0, 0)
            fcntl.ioctl(self._fd, termios.TIOCSWINSZ, winsize)
        except Exception:
            pass

    def close(self):
        self._running = False
        try:
            if _IS_WINDOWS and hasattr(self, "_proc"):
                self._proc.terminate()
            elif self._fd is not None:
                import signal
                os.kill(self._pid, signal.SIGTERM)
                os.close(self._fd)
        except Exception:
            pass
        self._fd = None
        self._pid = None


class PtyWebSocketClient:
    """Connects to backend /ws/agent/{device_id} and handles PTY sessions."""

    def __init__(self, server_url: str, device_id: str, reconnect_interval: int = 5, tls_verify: bool = True):
        self._server_url = server_url.rstrip("/")
        self._device_id = device_id
        self._reconnect_interval = reconnect_interval
        self._tls_verify = tls_verify
        self._session: PtySession | None = None
        self._running = False
        self._thread: threading.Thread | None = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="pty-ws")
        self._thread.start()
        logger.info("PTY WebSocket client started for device %s", self._device_id)

    def stop(self):
        self._running = False
        if self._session:
            self._session.close()
            self._session = None

    def _ws_url(self) -> str:
        base = self._server_url.replace("https://", "wss://").replace("http://", "ws://")
        return f"{base}/ws/agent/{self._device_id}"

    def _run_loop(self):
        while self._running:
            try:
                self._connect_and_serve()
            except Exception as e:
                logger.warning("PTY WS disconnected (%s), reconnecting in %ds", e, self._reconnect_interval)
            if self._running:
                time.sleep(self._reconnect_interval)

    def _connect_and_serve(self):
        try:
            import websocket as _ws_module  # websocket-client
        except ImportError:
            logger.error("websocket-client not installed, PTY terminal unavailable")
            time.sleep(60)
            return

        url = self._ws_url()
        logger.info("Connecting PTY WS to %s", url)

        import ssl as _ssl
        ssl_opt: dict = {}
        if not self._tls_verify:
            ssl_opt = {"cert_reqs": _ssl.CERT_NONE, "check_hostname": False}
        elif self._server_url.startswith("https://") or self._server_url.startswith("wss://"):
            # CentOS 7 has an outdated CA bundle — use certifi as fallback
            try:
                import certifi
                ssl_opt = {"ca_certs": certifi.where()}
            except ImportError:
                pass

        ws = _ws_module.WebSocket(sslopt=ssl_opt)
        ws.connect(url, timeout=30)
        logger.info("PTY WS connected")

        def _send_output(data: bytes):
            try:
                ws.send_binary(data)
            except Exception as e:
                logger.warning("PTY send error: %s", e)

        while self._running:
            try:
                raw = ws.recv()
            except Exception:
                break

            if not raw:
                continue

            # Parse control frames (JSON text)
            if isinstance(raw, str):
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg_type = msg.get("type")

                if msg_type == "open_pty":
                    if self._session:
                        self._session.close()
                    cols = int(msg.get("cols", 220))
                    rows = int(msg.get("rows", 50))
                    self._session = PtySession(_send_output, cols=cols, rows=rows)
                    self._session.start()
                    logger.info("PTY session opened (%dx%d)", cols, rows)

                elif msg_type == "close_pty":
                    if self._session:
                        self._session.close()
                        self._session = None
                    logger.info("PTY session closed")

                elif msg_type == "resize":
                    if self._session:
                        self._session.resize(int(msg.get("cols", 80)), int(msg.get("rows", 24)))

                elif msg_type == "input":
                    if self._session:
                        data_b64 = msg.get("data", "")
                        self._session.write(base64.b64decode(data_b64))

            elif isinstance(raw, bytes):
                # Raw input bytes from browser (xterm.js sends keystrokes as binary)
                if self._session:
                    self._session.write(raw)

        if self._session:
            self._session.close()
            self._session = None
        ws.close()
