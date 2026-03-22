"""Helpers for reading prebuilt agent release artifacts.

Production no longer builds Windows installers on demand. Instead, the backend
reads a release manifest that points to already-built artifacts published by CI.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_MANIFEST_PATH = (
    Path(__file__).resolve().parent / "agent_releases.json"
)


def _manifest_path() -> Path:
    configured = os.getenv("AGENT_RELEASES_MANIFEST")
    if configured:
        return Path(configured)
    return DEFAULT_MANIFEST_PATH


def load_release_catalog() -> dict[str, Any]:
    """Load the release catalog from disk.

    Returns an empty stable catalog when the manifest does not exist yet so the
    portal can stay functional before the first Windows release is published.
    """
    path = _manifest_path()
    if not path.exists():
        return {"channel": "stable", "releases": []}

    with path.open("r", encoding="utf-8") as fh:
        data = json.load(fh)

    if not isinstance(data, dict):
        raise ValueError("Agent release manifest must be a JSON object")

    releases = data.get("releases", [])
    if not isinstance(releases, list):
        raise ValueError("Agent release manifest 'releases' must be a list")

    return {
        "channel": str(data.get("channel", "stable")),
        "generated_at": data.get("generated_at"),
        "releases": releases,
    }


def get_latest_release() -> dict[str, Any] | None:
    """Return the first release entry from the manifest.

    Convention: CI writes the newest release first.
    """
    catalog = load_release_catalog()
    releases = catalog["releases"]
    return releases[0] if releases else None


def find_artifact(fmt: str, arch: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Find the latest artifact matching format and architecture."""
    release = get_latest_release()
    if not release:
        return None, None

    artifacts = release.get("artifacts", [])
    for artifact in artifacts:
        if artifact.get("format") == fmt and artifact.get("arch") == arch:
            return release, artifact
    return release, None


def find_linux_proxy_bundle() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Latest release artifact: Linux proxy-agent tarball (format linux-tarball, arch amd64)."""
    release = get_latest_release()
    if not release:
        return None, None
    for artifact in release.get("artifacts", []):
        if artifact.get("format") == "linux-tarball" and artifact.get("arch") == "amd64":
            return release, artifact
    return release, None
