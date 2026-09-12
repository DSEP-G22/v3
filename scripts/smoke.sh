#!/usr/bin/env bash
# Smoke test through the edge. Later phases append sign-up, pay, chat and SSE checks.
set -euo pipefail
BASE="${BASE:-http://localhost:8080}"
curl -fsS "$BASE/healthz" >/dev/null && echo "ok  edge /healthz"
