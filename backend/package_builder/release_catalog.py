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
    """Return the release with the highest semantic version from the manifest."""
    catalog = load_release_catalog()
    releases = catalog["releases"]
    if not releases:
        return None

    def _ver_key(r: dict) -> list[int]:
        parts: list[int] = []
        for chunk in str(r.get("version", "")).split("."):
            try:
                parts.append(int(chunk))
            except ValueError:
                parts.append(0)
        return parts

    return max(releases, key=_ver_key)


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


# Maps distro slug → artifact format stored in agent_releases.json
_DISTRO_FORMAT_MAP: dict[str, str] = {
    # Debian/Ubuntu family
    "deb":        "linux-deb",
    "debian":     "linux-deb",
    "ubuntu":     "linux-deb",
    # RedHat/CentOS/Rocky/AlmaLinux family
    "rpm":        "linux-rpm",
    "centos":     "linux-rpm",
    "centos7":    "linux-rpm",
    "centos8":    "linux-rpm",
    "centos9":    "linux-rpm",
    "rhel":       "linux-rpm",
    "rhel7":      "linux-rpm",
    "rhel8":      "linux-rpm",
    "rhel9":      "linux-rpm",
    "almalinux":  "linux-rpm",
    "rocky":      "linux-rpm",
    "fedora":     "linux-rpm",
    # Generic / legacy
    "linux":      "linux-binary",
    "generic":    "linux-binary",
}


def distro_to_format(distro: str) -> str:
    """Convert a distro slug to the artifact format key.

    Falls back to 'linux-deb' (widest glibc compatibility among new formats)
    when the distro is unknown, then 'linux-binary' for legacy manifests.
    """
    return _DISTRO_FORMAT_MAP.get(distro.lower().strip(), "linux-deb")


def find_linux_artifact(distro: str) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Find the best Linux artifact for the requested distro.

    Resolution order:
    1. Exact format from _DISTRO_FORMAT_MAP (e.g. linux-rpm for centos7)
    2. 'linux-binary' legacy fallback (pre-matrix releases)
    3. Any artifact whose format starts with 'linux-'
    """
    release = get_latest_release()
    if not release:
        return None, None

    fmt = distro_to_format(distro)
    artifacts = release.get("artifacts", [])

    # Primary match
    for artifact in artifacts:
        if artifact.get("format") == fmt and artifact.get("arch") == "amd64":
            return release, artifact

    # Legacy fallback: old releases only had 'linux-binary'
    for artifact in artifacts:
        if artifact.get("format") == "linux-binary" and artifact.get("arch") == "amd64":
            return release, artifact

    # Last resort: any linux artifact
    for artifact in artifacts:
        if str(artifact.get("format", "")).startswith("linux-"):
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
