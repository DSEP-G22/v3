#!/usr/bin/env bash
# The whole master test plan (docs/TEST-PLAN.md) in one command, on a throwaway database.
#
#   bash scripts/test-plan.sh                 # everything, stack started from compose.test.yaml
#   STEPS="system browser" bash scripts/test-plan.sh
#
# Evidence lands in reports/<date>/: one log per step, JUnit XML, k6 summaries, the mobile
# screenshots and a PNG of every terminal log (for the written report). The same script runs in
# GitHub Actions (.github/workflows/test-plan.yml). Every step runs even when an earlier one
# fails; the exit code is non-zero if any did.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$PWD"
OUT="${OUT:-reports/$(date +%Y-%m-%d)}"
STEPS="${STEPS:-unit stack system browser scenario load shots}"
export LANKA_URL="${LANKA_URL:-http://localhost:8080}"
# Every docker compose call below, and the ones the resilience tests make, use the test overlay:
# its own Postgres, never the shared Neon database.
export COMPOSE_PATH_SEPARATOR=":"
export COMPOSE_FILE="${COMPOSE_FILE:-compose.yaml:compose.test.yaml}"
mkdir -p "$OUT/logs" "$OUT/screens/mobile" "$OUT/screens/terminal"
touch "$OUT/summary.tsv"
failed=0

# step <name> <command...>: run it, keep its output, record pass or fail and how long it took.
step() {
  local name="$1"; shift
  local log="$OUT/logs/$name.log" start=$SECONDS
  echo "== $name: $*" | tee "$log"
  if "$@" 2>&1 | tee -a "$log"; then status=PASS; else status=FAIL; failed=1; fi
  # A rerun of one step (STEPS=system) replaces that step's line and keeps the others.
  { grep -v "^$name	" "$OUT/summary.tsv" || true; printf '%s\t%s\t%ss\n' "$name" "$status" "$((SECONDS - start))"; } \
    | sort > "$OUT/summary.tmp" && mv "$OUT/summary.tmp" "$OUT/summary.tsv"
  grep "^$name	" "$OUT/summary.tsv"
}
want() { [[ " $STEPS " == *" $1 "* ]]; }

want unit && step 01-unit bash scripts/test-all.sh

if want stack; then
  # --wait reports business-sim (no health check by design) as an error; the smoke test decides.
  step 02-stack bash -c 'docker compose up -d --wait >/dev/null 2>&1; docker compose ps --format "table {{.Service}}\t{{.Status}}" && bash scripts/smoke.sh'
fi

if want system; then
  step 03-system env LANKA_RESILIENCE=1 uv run --with httpx --with pytest python -m pytest tests/system -v \
    -p no:cacheprovider --junitxml="$OUT/junit-system.xml"
fi

if want browser; then
  step 04-browser bash -c "cd web && SHOTS_DIR='$ROOT/$OUT/screens/mobile' PLAYWRIGHT_JUNIT_OUTPUT_NAME='$ROOT/$OUT/junit-browser.xml' npx playwright test --reporter=list,junit"
fi

if want scenario; then
  step 05-demo-flow uv run --with httpx python scripts/demo_flow.py --strict
  step 06-hot-swap uv run --with httpx python scripts/verify_hot_swap.py
fi

if want load; then
  step 07-load env SUMMARY="$OUT/load-ack.json" bash scripts/load.sh
fi

if want shots; then
  # Last, so it pictures every log above, including its own predecessors' failures.
  (cd web && node scripts/term-shots.mjs "$ROOT/$OUT/logs" "$ROOT/$OUT/screens/terminal") >/dev/null 2>&1 \
    || echo "terminal screenshots failed" >&2
fi

echo
echo "Summary ($OUT/summary.tsv):"
column -t -s $'\t' "$OUT/summary.tsv" 2>/dev/null || cat "$OUT/summary.tsv"
exit "$failed"
