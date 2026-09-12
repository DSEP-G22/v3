#!/usr/bin/env bash
# Export the router classifier to ONNX (needs torch locally). NLLB and whisper are converted
# inside their Dockerfiles, so `docker compose build translation audio` covers those.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run --with torch --with torchvision --with onnx python models/export_router_onnx.py "$@"
