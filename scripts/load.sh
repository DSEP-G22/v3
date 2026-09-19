#!/usr/bin/env bash
# k6 scenarios from load/. Uses a local k6 if present, otherwise the grafana/k6 image.
#   bash scripts/load.sh                                   # load/ack.js, PLAN section 4 thresholds
#   SCRIPT=load/browse.js LANKA_URL=https://... bash scripts/load.sh   # read-only, safe on production
# SUMMARY=path.json keeps k6's end of test summary for the report.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="${LANKA_URL:-http://localhost:8080}"
SCRIPT="${SCRIPT:-load/ack.js}"
EMAIL="${EMAIL:-amara@customers.lankalink.example.lk}"
PASSWORD="${SEED_CUSTOMER_PASSWORD:-Lanka#2026}"
ARGS=(-e BASE="$BASE" -e EMAIL="$EMAIL" -e PASSWORD="$PASSWORD")
if command -v k6 >/dev/null; then
  k6 run "${ARGS[@]}" ${SUMMARY:+--summary-export "$SUMMARY"} "$SCRIPT"
else
  # MSYS_NO_PATHCONV: Git Bash on Windows rewrites /work into a C:\ path before Docker sees it.
  MSYS_NO_PATHCONV=1 docker run --rm -i --network host -v "$PWD:/work" -w /work grafana/k6 run \
    "${ARGS[@]}" ${SUMMARY:+--summary-export "/work/$SUMMARY"} "/work/$SCRIPT"
fi
