#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] || { echo "no .env: cp .env.example .env and fill NEON_KEY"; exit 1; }
grep -Eq '^\s*NEON_KEY\s*=\s*\S' .env || { echo ".env has no NEON_KEY"; exit 1; }
docker compose up -d --build --wait "$@"
echo "Lanka Link v3 is up: http://localhost:8080"
