#!/usr/bin/env python3
"""Add or replace linux-tarball artifact on an existing release entry in agent_releases.json."""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--version", required=True, help="Release version string, e.g. 1.8.0")
    p.add_argument("--url", required=True)
    p.add_argument("--sha256", required=True)
    p.add_argument("--filename", required=True)
    p.add_argument("--size-bytes", type=int, required=True)
    args = p.parse_args()

    path = Path(args.manifest)
    data = json.loads(path.read_text(encoding="utf-8"))
    releases = data.get("releases", [])
    found = False
    for rel in releases:
        if isinstance(rel, dict) and str(rel.get("version")) == args.version:
            arts = [a for a in rel.get("artifacts", []) if isinstance(a, dict)]
            arts = [
                a
                for a in arts
                if not (
                    a.get("format") == "linux-tarball" and a.get("arch") == "amd64"
                )
            ]
            arts.append(
                {
                    "format": "linux-tarball",
                    "arch": "amd64",
                    "filename": args.filename,
                    "url": args.url,
                    "sha256": args.sha256,
                    "size_bytes": args.size_bytes,
                    "notes": "Linux proxy-agent tarball (GitHub Actions)",
                }
            )
            rel["artifacts"] = arts
            found = True
            break

    if not found:
        raise SystemExit(f"No release with version {args.version!r} in manifest")

    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
