#!/usr/bin/env python3
"""Inject MQTT-over-WebSocket location block into an Nginx server config.

Usage: python3 inject_nginx_mqtt.py /path/to/nginx.conf

Idempotent — does nothing if the location block is already present.
Inserts the block just before the last closing brace of the file,
which is the closing brace of the outermost server {} block.
"""

import pathlib
import sys

MQTT_BLOCK = """
    # MQTT over WebSocket (WSS) — proxied through port 443
    location /mqtt {
        proxy_pass         http://127.0.0.1:8083/mqtt;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       $host;
        proxy_read_timeout 86400s;
        proxy_send_timeout 86400s;
    }
"""

TERMINAL_WS_BLOCK = """
    # PTY terminal WebSocket relay — agent and browser connect here
    location /ws/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Upgrade    $http_upgrade;
        proxy_set_header   Connection "upgrade";
        proxy_set_header   Host       $host;
        proxy_set_header   X-Real-IP  $remote_addr;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
"""

PACKAGES_BLOCK = """
    # Package generation — may download ~14 MB from GitHub on first request
    location /api/packages/generate {
        proxy_pass         http://127.0.0.1:3002;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
        proxy_buffering    off;
    }

    # Backend package API — long timeout for GitHub EXE download
    location /api/v1/packages/ {
        proxy_pass         http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header   Host              $host;
        proxy_set_header   X-Real-IP         $remote_addr;
        proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header   X-Forwarded-Proto $scheme;
        proxy_read_timeout 180s;
        proxy_send_timeout 180s;
        proxy_buffering    off;
    }
"""


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: inject_nginx_mqtt.py <nginx_conf_path>", file=sys.stderr)
        return 1

    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8")
    changed = False

    for marker, block, label in [
        ("location /mqtt", MQTT_BLOCK, "/mqtt WebSocket proxy"),
        ("location /ws/", TERMINAL_WS_BLOCK, "/ws/ PTY terminal WebSocket proxy"),
        ("location /api/packages/generate", PACKAGES_BLOCK, "/api/packages/generate + /api/v1/packages/ timeout blocks"),
    ]:
        if marker in content:
            print(f"[nginx-mqtt] {label} already configured — skipping.")
            continue
        idx = content.rfind("}")
        if idx == -1:
            print("[nginx-mqtt] No closing brace found — cannot inject.", file=sys.stderr)
            return 1
        content = content[:idx] + block + content[idx:]
        changed = True
        print(f"[nginx-mqtt] Injected {label} into {path}")

    if changed:
        path.write_text(content, encoding="utf-8")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
