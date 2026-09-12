#!/usr/bin/env bash
# Re-run migrations and the idempotent genesis against the configured Neon and Timescale.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose run --rm migrate
docker compose run --rm seed
