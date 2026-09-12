#!/usr/bin/env bash
# k6 thresholds from PLAN section 4. Uses a local k6 if present, otherwise the grafana/k6 image.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="${LANKA_URL:-http://localhost:8080}"
EMAIL="${EMAIL:-amara@customers.lankalink.example.lk}"
PASSWORD="${SEED_CUSTOMER_PASSWORD:-Lanka#2026}"
if command -v k6 >/dev/null; then
  k6 run -e BASE="$BASE" -e EMAIL="$EMAIL" -e PASSWORD="$PASSWORD" load/ack.js
else
  docker run --rm -i --network host -v "$PWD/load:/load" grafana/k6 run \
    -e BASE="$BASE" -e EMAIL="$EMAIL" -e PASSWORD="$PASSWORD" /load/ack.js
fi
