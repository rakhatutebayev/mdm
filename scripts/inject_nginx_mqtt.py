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


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: inject_nginx_mqtt.py <nginx_conf_path>", file=sys.stderr)
        return 1

    path = pathlib.Path(sys.argv[1])
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 1

    content = path.read_text(encoding="utf-8")

    if "location /mqtt" in content:
        print(f"[nginx-mqtt] Already configured in {path} — skipping.")
        return 0

    # Insert before the last closing brace (end of last server block)
    idx = content.rfind("}")
    if idx == -1:
        print("[nginx-mqtt] No closing brace found — cannot inject.", file=sys.stderr)
        return 1

    new_content = content[:idx] + MQTT_BLOCK + content[idx:]
    path.write_text(new_content, encoding="utf-8")
    print(f"[nginx-mqtt] Injected /mqtt WebSocket proxy into {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
