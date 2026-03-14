#!/usr/bin/env bash
# =============================================================================
# build-agent.sh — Build NOCKO Agent Windows EXE on Linux using Docker + Wine
# =============================================================================
# Usage:
#   ./build-agent.sh              # build exe and copy to server binary store
#   ./build-agent.sh --no-upload  # build only, keep in ./dist-win/
#   ./build-agent.sh --help
#
# Requirements:
#   - Docker (running)
#   - agent-gui/ directory (this script should be in the project root)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_DIR="$SCRIPT_DIR/agent-gui"
OUT_DIR="$SCRIPT_DIR/dist-win"
SERVER_BIN_DIR="/var/nocko/agent-binaries"
IMAGE_NAME="nocko-agent-builder"
EXE_NAME="NOCKO-Agent-Setup.exe"

NO_UPLOAD=false
for arg in "$@"; do
  case $arg in
    --no-upload) NO_UPLOAD=true ;;
    --help|-h)
      echo "Usage: $0 [--no-upload] [--help]"
      echo ""
      echo "  --no-upload   Build the exe but don't copy to server directory"
      echo "  --help        Show this help"
      exit 0
      ;;
  esac
done

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║    NOCKO Agent — Windows EXE Builder (Linux/Docker)     ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""

# Check Docker
if ! command -v docker &>/dev/null; then
  echo "❌  Docker not found. Install Docker and try again."
  exit 1
fi

if ! docker info &>/dev/null; then
  echo "❌  Docker daemon is not running."
  exit 1
fi

echo "🐳  Building Docker image: $IMAGE_NAME"
docker build \
  --file "$AGENT_DIR/Dockerfile.build" \
  --tag "$IMAGE_NAME:latest" \
  "$AGENT_DIR"

echo ""
echo "📦  Extracting built EXE..."
mkdir -p "$OUT_DIR"

# Run the container, extract /output to local
CONTAINER_ID=$(docker create "$IMAGE_NAME:latest")
docker cp "$CONTAINER_ID:/output/$EXE_NAME" "$OUT_DIR/$EXE_NAME"
docker rm "$CONTAINER_ID" >/dev/null

EXE_SIZE=$(du -sh "$OUT_DIR/$EXE_NAME" | cut -f1)
echo "✅  Built: $OUT_DIR/$EXE_NAME  ($EXE_SIZE)"

if [ "$NO_UPLOAD" = true ]; then
  echo ""
  echo "ℹ️   --no-upload: skipping copy to server directory."
  echo "    EXE is at: $OUT_DIR/$EXE_NAME"
  exit 0
fi

# Copy to server binary store (used by Package Builder API)
echo ""
echo "🚚  Copying to $SERVER_BIN_DIR/..."
mkdir -p "$SERVER_BIN_DIR"
cp "$OUT_DIR/$EXE_NAME" "$SERVER_BIN_DIR/$EXE_NAME"
echo "✅  EXE available for Package Builder!"
echo ""
echo "Done. Admins can now create Windows packages from the MDM dashboard."
echo ""
