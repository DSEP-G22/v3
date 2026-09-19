#!/usr/bin/env bash
# Everything CI runs that needs no containers.
set -euo pipefail
cd "$(dirname "$0")/.."

uv sync --all-packages
uv run ruff check .
uv run pytest packages -q
for svc in gateway business inquiry triage translation; do
  (cd "services/$svc" && uv run python -m pytest tests -q)
done
(cd services/business && uv run python -m app.clock && uv run python -m app.fixtures ../grounding/tests/fixtures/prefetch.json)
(cd services/grounding && uv run python -m pytest tests -q)
(cd services/orchestrator && uv run python -m app.fusion)
(cd services/audio && uv run python -m app.confidence)
(cd services/image && uv run python -m app.led)
(cd services/knowledge && uv run python -m app.diagnose)
(cd services/response && uv run python -m app.policy)
uv run pytest tests/architecture -q
(cd services/auth && npm test)
(cd web && npx tsc --noEmit && ! grep -rEn 'faker|mockData|placeholderData' app components lib)
echo "test-all OK"
