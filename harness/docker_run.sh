#!/usr/bin/env bash
# Builds and runs the Pixel Proof harness inside a Docker container.
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
# NIGHTSHIFT_HARNESS_IMAGE is the name from before the October 28 rename, still honoured.
IMAGE_NAME="${PIXELPROOF_HARNESS_IMAGE:-${NIGHTSHIFT_HARNESS_IMAGE:-pixelproof-harness:latest}}"

if [[ "${1:-}" == "--build-only" ]]; then
    echo "Building harness container ($IMAGE_NAME)..."
    docker build --platform linux/amd64 -f "$REPO/Dockerfile.harness" -t "$IMAGE_NAME" "$REPO"
    exit 0
fi

# Build image if not present
if ! docker image inspect "$IMAGE_NAME" >/dev/null 2>&1; then
    echo "Building harness container image ($IMAGE_NAME)..."
    docker build --platform linux/amd64 -f "$REPO/Dockerfile.harness" -t "$IMAGE_NAME" "$REPO"
fi

mkdir -p "$REPO/runs"
echo "Running harness container ($IMAGE_NAME)..."
docker run --rm \
    --platform linux/amd64 \
    -v "$REPO/runs:/workspace/runs" \
    "$IMAGE_NAME" "$@"

