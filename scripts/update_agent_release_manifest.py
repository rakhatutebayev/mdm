#!/usr/bin/env python3
"""Update backend/package_builder/agent_releases.json from built release assets."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_asset(value: str) -> dict[str, str]:
    parts = value.split(":", 2)
    if len(parts) != 3:
        raise argparse.ArgumentTypeError(
            "Asset must be in the form <format>:<arch>:<path>"
        )

    fmt, arch, path = parts
    if fmt != "exe":
        raise argparse.ArgumentTypeError("Asset format must be 'exe'")
    if arch not in {"x64", "x86"}:
        raise argparse.ArgumentTypeError("Asset arch must be 'x64' or 'x86'")

    return {"format": fmt, "arch": arch, "path": path}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--generated-at", required=True)
    parser.add_argument(
        "--asset",
        action="append",
        type=parse_asset,
        default=[],
        help="Repeatable: <format>:<arch>:<path>",
    )
    args = parser.parse_args()

    manifest_path = Path(args.manifest)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
    else:
        data = {"channel": "stable", "generated_at": None, "releases": []}

    release = {
        "version": args.version,
        "tag": args.tag,
        "artifacts": [],
    }

    for asset in args.asset:
        path = Path(asset["path"])
        if not path.exists():
            raise FileNotFoundError(f"Asset does not exist: {path}")

        filename = path.name
        release["artifacts"].append(
            {
                "format": asset["format"],
                "arch": asset["arch"],
                "filename": filename,
                "url": f"https://github.com/{args.repo}/releases/download/{args.tag}/{filename}",
                "sha256": sha256_of(path),
                "size_bytes": path.stat().st_size,
                "notes": "Published by GitHub Actions Windows release workflow",
            }
        )

    releases = [
        item for item in data.get("releases", [])
        if isinstance(item, dict) and item.get("version") != args.version
    ]
    releases.insert(0, release)

    data["channel"] = "stable"
    data["generated_at"] = args.generated_at
    data["releases"] = releases

    manifest_path.write_text(
        json.dumps(data, indent=2) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
