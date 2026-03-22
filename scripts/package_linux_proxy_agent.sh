#!/usr/bin/env bash
# Build nocko-proxy-agent-<version>-linux-amd64.tar.gz from proxy-agent/ (repo root).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VERSION="${1:?usage: $0 <version>}"
OUT_DIR="${ROOT}/dist"
mkdir -p "$OUT_DIR"
NAME="nocko-proxy-agent-${VERSION}-linux-amd64.tar.gz"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
COPYFILE_DISABLE=1 tar czf "$TMP/$NAME" \
  --exclude '.git' --exclude '__pycache__' --exclude '*.pyc' \
  --exclude '.pytest_cache' --exclude '.venv' \
  -C "$ROOT" proxy-agent
mv "$TMP/$NAME" "$OUT_DIR/$NAME"
echo "OK: $OUT_DIR/$NAME ($(wc -c < "$OUT_DIR/$NAME") bytes)"
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "$OUT_DIR/$NAME"
else
  shasum -a 256 "$OUT_DIR/$NAME"
fi
