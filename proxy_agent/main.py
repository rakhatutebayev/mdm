#!/usr/bin/env python3
"""NOCKO Proxy Agent bootstrap and runtime."""
from __future__ import annotations

import argparse
import json
import socket
import sys
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from proxy_agent.collectors.redfish import RedfishTarget, collect_target as collect_redfish_target
from proxy_agent.collectors.snmp import SnmpTarget, collect_target
from proxy_agent.mqtt_client import ProxyMqttClient
from proxy_agent.state import record_run_failure, record_run_start, record_run_success
from proxy_agent.templates import resolve_template


DEFAULT_CONFIG_PATH = Path.home() / ".config" / "nocko-proxy-agent" / "config.json"


def default_hostname() -> str:
    return socket.gethostname()


def detect_primary_ip() -> str:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return ""
    finally:
        sock.close()


def detect_primary_mac() -> str:
    try:
        value = uuid.getnode()
    except Exception:
        return ""
    if value is None:
        return ""
    return ":".join(f"{(value >> shift) & 0xFF:02X}" for shift in range(40, -1, -8))


def load_config(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"Config file not found: {path}", file=sys.stderr)
        raise SystemExit(2)
    except json.JSONDecodeError as exc:
        print(f"Invalid JSON in config file {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)


def save_config(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def normalize_server_url(value: str) -> str:
    return value.rstrip("/")


def parse_capabilities(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def build_snmp_targets(config: dict[str, Any]) -> list[SnmpTarget]:
    targets: list[SnmpTarget] = []
    collector_cfg = config.get("collectors", {})
    for item in collector_cfg.get("snmp_targets", []):
        targets.append(
            SnmpTarget(
                name=item.get("name", "SNMP target"),
                community=item.get("community", "public"),
                port=int(item.get("port", 161)),
                timeout_s=float(item.get("timeout", 0.8)),
                retries=int(item.get("retries", 0)),
                hosts=item.get("hosts") or [],
                subnet=item.get("subnet") or None,
                workers=int(item.get("workers", 32)),
                template_key=item.get("template_key", ""),
                only_match=item.get("only_match", ""),
                ssh_username=item.get("ssh_username", ""),
                ssh_password=item.get("ssh_password", ""),
                ssh_port=int(item.get("ssh_port", 22)),
                perccli_path=item.get("perccli_path", "/opt/lsi/perccli/perccli"),
                perccli_controller=int(item.get("perccli_controller", 0)),
                idrac_storage_enabled=bool(item.get("idrac_storage_enabled", True)),
                storage_timeout_s=float(item["storage_timeout_s"])
                if item.get("storage_timeout_s") is not None
                else None,
            )
        )
    return targets


def build_redfish_targets(config: dict[str, Any]) -> list[RedfishTarget]:
    targets: list[RedfishTarget] = []
    collector_cfg = config.get("collectors", {})
    for item in collector_cfg.get("redfish_targets", []):
        targets.append(
            RedfishTarget(
                name=item.get("name", "Redfish target"),
                base_url=item["base_url"],
                username=item["username"],
                password=item["password"],
                verify_tls=bool(item.get("verify_tls", True)),
                timeout_s=float(item.get("timeout", 10.0)),
                template_key=item.get("template_key", ""),
                system_path=item.get("system_path", ""),
                manager_path=item.get("manager_path", ""),
            )
        )
    return targets


def normalize_assets(raw_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for raw_asset in raw_assets:
        template = resolve_template(raw_asset)
        normalized.append(template.normalize(raw_asset))
    return normalized


def build_payload(config: dict[str, Any]) -> dict[str, Any]:
    raw_assets: list[dict[str, Any]] = []
    enabled_collectors = {item.strip().lower() for item in config.get("collectors_enabled", ["snmp"]) if str(item).strip()}

    if "snmp" in enabled_collectors:
        for target in build_snmp_targets(config):
            try:
                raw_assets.extend(collect_target(target))
            except Exception as exc:
                print(f"SNMP collector failed for {target.name}: {exc}", file=sys.stderr)

    if "redfish" in enabled_collectors:
        for target in build_redfish_targets(config):
            try:
                raw_assets.extend(collect_redfish_target(target))
            except Exception as exc:
                print(f"Redfish collector failed for {target.name}: {exc}", file=sys.stderr)

    return {
        "agent_token": config["agent_token"],
        "agent": {
            "hostname": config.get("hostname") or default_hostname(),
            "ip_address": config.get("ip_address") or detect_primary_ip(),
            "mac_address": config.get("mac_address") or detect_primary_mac(),
            "portal_url": config.get("portal_url", ""),
            "version": config.get("version", "0.1.0"),
            "site_name": config.get("site_name", ""),
            "capabilities": config.get("collectors_enabled", ["snmp"]),
        },
        "assets": normalize_assets(raw_assets),
    }


def post_ingest(config: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    server = normalize_server_url(config["portal_url"])
    response = requests.post(
        f"{server}/api/v1/discovery/ingest",
        json=payload,
        timeout=float(config.get("request_timeout_seconds", 30)),
    )
    response.raise_for_status()
    return response.json()


def perform_sync(config: dict[str, Any], verbose: bool = False) -> dict[str, Any]:
    record_run_start()
    payload = build_payload(config)
    if verbose:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    asset_count = len(payload.get("assets", []))
    result = post_ingest(config, payload)
    record_run_success(result=result, asset_count=asset_count)
    return {
        "asset_count": asset_count,
        "result": result,
    }


def run_once(config: dict[str, Any], verbose: bool = False) -> int:
    sync_result = perform_sync(config, verbose=verbose)
    print(json.dumps(sync_result["result"], ensure_ascii=False, indent=2))
    return 0


def command_register(args: argparse.Namespace) -> int:
    config_path = Path(args.config).expanduser()
    payload = {
        "portal_url": normalize_server_url(args.server),
        "agent_id": args.agent_id,
        "agent_token": args.token,
        "agent_name": args.name,
        "site_name": args.site,
        "hostname": args.hostname or default_hostname(),
        "ip_address": args.ip or detect_primary_ip(),
        "mac_address": detect_primary_mac(),
        "version": args.version,
        "interval_seconds": args.interval,
        "request_timeout_seconds": 30,
        "collectors_enabled": parse_capabilities(args.capabilities),
        "mqtt_enabled": True,
        "mqtt_host": "",
        "mqtt_port": 443,
        "mqtt_transport": "websockets",
        "mqtt_path": "/mqtt",
        "mqtt_tls": True,
        "mqtt_tls_verify": True,
        "mqtt_tls_allow_insecure_fallback": False,
        "mqtt_heartbeat_interval_seconds": 30,
        "collectors": {
            "snmp_targets": [],
            "redfish_targets": [],
        },
    }
    save_config(config_path, payload)
    print(f"Proxy Agent config written to {config_path}")
    return 0


def command_run(args: argparse.Namespace) -> int:
    config = load_config(Path(args.config).expanduser())
    interval = int(config.get("interval_seconds", 300))
    mqtt_client: ProxyMqttClient | None = None

    if bool(config.get("mqtt_enabled", True)):
        mqtt_client = ProxyMqttClient(
            config=config,
            run_sync_fn=lambda: perform_sync(config, verbose=False),
            heartbeat_interval=int(config.get("mqtt_heartbeat_interval_seconds", 30)),
        )
        mqtt_client.start()

    try:
        while True:
            try:
                run_once(config, verbose=args.verbose)
            except requests.HTTPError as exc:
                body = exc.response.text if exc.response is not None else str(exc)
                record_run_failure(body)
                print(f"Ingest failed: {body}", file=sys.stderr)
                if args.once:
                    return 1
            except Exception as exc:
                record_run_failure(str(exc))
                print(f"Proxy Agent cycle failed: {exc}", file=sys.stderr)
                if args.once:
                    return 1

            if args.once:
                return 0

            time.sleep(max(5, interval))
    finally:
        if mqtt_client:
            mqtt_client.stop()


def command_serve(args: argparse.Namespace) -> int:
    from proxy_agent.web import serve_console

    serve_console(
        config_path=Path(args.config).expanduser(),
        host=args.bind,
        port=args.port,
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="NOCKO Proxy Agent")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register_parser = subparsers.add_parser("register", help="Write local Proxy Agent config")
    register_parser.add_argument("--server", required=True, help="Portal base URL, e.g. https://portal.example.com")
    register_parser.add_argument("--agent-id", default="", help="Proxy Agent ID issued by portal")
    register_parser.add_argument("--token", required=True, help="Proxy Agent auth token")
    register_parser.add_argument("--name", required=True, help="Proxy Agent display name")
    register_parser.add_argument("--site", default="", help="Site name")
    register_parser.add_argument("--hostname", default="", help="Override detected hostname")
    register_parser.add_argument("--ip", default="", help="Override detected source IP")
    register_parser.add_argument("--version", default="0.1.0", help="Agent version")
    register_parser.add_argument("--interval", type=int, default=300, help="Poll interval in seconds")
    register_parser.add_argument(
        "--capabilities",
        default="snmp,redfish,lldp",
        help="Comma-separated collector capabilities",
    )
    register_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config output path")
    register_parser.set_defaults(func=command_register)

    run_parser = subparsers.add_parser("run", help="Start collection loop")
    run_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config file path")
    run_parser.add_argument("--once", action="store_true", help="Run one collection cycle and exit")
    run_parser.add_argument("--verbose", action="store_true", help="Print full outgoing payload")
    run_parser.set_defaults(func=command_run)

    serve_parser = subparsers.add_parser("serve", help="Start local web console")
    serve_parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="Config file path")
    serve_parser.add_argument("--bind", default="127.0.0.1", help="Bind address")
    serve_parser.add_argument("--port", type=int, default=8771, help="HTTP port")
    serve_parser.set_defaults(func=command_serve)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
