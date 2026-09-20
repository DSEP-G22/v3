#!/usr/bin/env bash
# One off: rewrite this repository's history to drop the "Co-Authored-By: Claude" trailer from
# every commit message, and to remove the session token that one commit's k6 summary carried.
#
#   bash scripts/strip-claude-trailers.sh           # rewrite locally, then show what changed
#   PUSH=1 bash scripts/strip-claude-trailers.sh    # rewrite and force push main
#
# Rewriting published history changes every commit id after the first rewritten one. Anyone else
# with a clone has to reset to the new main. A backup branch is left behind (backup/pre-rewrite),
# so `git reset --hard backup/pre-rewrite` puts it back.
set -euo pipefail
cd "$(dirname "$0")/.."

tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

cat > "$tmp/msg.py" <<'PY'
import sys
msg = sys.stdin.read()
keep = [l for l in msg.splitlines() if not l.strip().lower().startswith("co-authored-by: claude")]
while keep and not keep[-1].strip():
    keep.pop()
sys.stdout.write("\n".join(keep) + "\n")
PY

cat > "$tmp/tree.py" <<'PY'
import json, os
# k6's exported summary carried setup_data, which held a session token. It is already out of the
# working tree; this takes it out of the history as well.
for f in ("docs/test-report/evidence/load-ack.json", "docs/test-report/evidence/load-browse.json"):
    if not os.path.exists(f):
        continue
    try:
        d = json.load(open(f, encoding="utf-8"))
    except Exception:
        continue
    if isinstance(d, dict) and "setup_data" in d:
        d.pop("setup_data")
        json.dump(d, open(f, "w", encoding="utf-8"), indent=2)
PY

git branch -f backup/pre-rewrite HEAD
echo "backup branch: backup/pre-rewrite at $(git rev-parse --short backup/pre-rewrite)"
before=$(git log --format='%H %b' | grep -ci 'co-authored-by: claude' || true)

FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f \
  --msg-filter "python '$tmp/msg.py'" \
  --tree-filter "python '$tmp/tree.py'" -- main

after=$(git log --format='%H %b' | grep -ci 'co-authored-by: claude' || true)
echo "commits carrying the trailer: $before before, $after after"
[ "$after" = "0" ] || { echo "the trailer is still present; not pushing" >&2; exit 1; }

# The token is out of the history now, so the allow list that excused it can go.
if [ -f .gitleaksignore ]; then
  git rm -q .gitleaksignore
  git commit -q -m "Drop the gitleaks allow list: the token is out of the history"
fi

docker run --rm -v "$PWD:/repo" zricethezav/gitleaks:v8.28.0 git /repo --no-banner --redact

if [ "${PUSH:-0}" = "1" ]; then
  git push --force-with-lease origin main
  echo "pushed; the next release and deploy run against the new ids"
else
  echo "not pushed. Check 'git log', then: git push --force-with-lease origin main"
fi
