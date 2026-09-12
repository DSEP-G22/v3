#!/usr/bin/env bash
# Build and push every image by hand (release.yml does this on main). Needs `docker login ghcr.io`.
#   GHCR_OWNER=you V3_TAG=latest scripts/publish-images.sh
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GHCR_OWNER:?set GHCR_OWNER to your GitHub user}"
export GHCR_OWNER V3_TAG="${V3_TAG:-latest}"
docker compose build
docker compose push
