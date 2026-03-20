"""Persistent runtime state for Proxy Agent."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_STATE_PATH = Path.home() / ".config" / "nocko-proxy-agent" / "state.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_state(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "last_success_at": None,
            "last_error": "",
            "last_result": None,
            "last_asset_count": 0,
        }
    except Exception:
        return {
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "last_success_at": None,
            "last_error": "Could not parse state file.",
            "last_result": None,
            "last_asset_count": 0,
        }
    if not isinstance(payload, dict):
        return {
            "last_run_started_at": None,
            "last_run_finished_at": None,
            "last_success_at": None,
            "last_error": "Invalid state payload.",
            "last_result": None,
            "last_asset_count": 0,
        }
    return payload


def save_state(payload: dict[str, Any], path: Path = DEFAULT_STATE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def record_run_start(path: Path = DEFAULT_STATE_PATH) -> dict[str, Any]:
    state = load_state(path)
    state["last_run_started_at"] = utc_now_iso()
    save_state(state, path)
    return state


def record_run_success(
    result: dict[str, Any],
    asset_count: int,
    path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    state = load_state(path)
    now = utc_now_iso()
    state["last_run_finished_at"] = now
    state["last_success_at"] = now
    state["last_error"] = ""
    state["last_result"] = result
    state["last_asset_count"] = asset_count
    save_state(state, path)
    return state


def record_run_failure(
    error_message: str,
    asset_count: int = 0,
    path: Path = DEFAULT_STATE_PATH,
) -> dict[str, Any]:
    state = load_state(path)
    state["last_run_finished_at"] = utc_now_iso()
    state["last_error"] = error_message
    state["last_asset_count"] = asset_count
    save_state(state, path)
    return state
