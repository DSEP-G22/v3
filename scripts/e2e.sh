#!/usr/bin/env bash
# Playwright against a running stack on :8080 (scripts/up first).
set -euo pipefail
cd "$(dirname "$0")/../web"
npx playwright install --with-deps chromium
LANKA_URL="${LANKA_URL:-http://localhost:8080}" npx playwright test "$@"
