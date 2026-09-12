#!/usr/bin/env bash
# Create the GitHub repo and push. Run it yourself after confirming the name:
#   scripts/repo-init.sh lanka-link-v3 [--private]
set -euo pipefail
cd "$(dirname "$0")/.."

name="${1:?usage: scripts/repo-init.sh <repo-name> [--private|--public]}"
visibility="${2:---private}"

[ -f .gitignore ] || { echo ".gitignore missing; refusing to commit" >&2; exit 1; }
grep -qx '.env' .gitignore || { echo ".env is not ignored; refusing to commit" >&2; exit 1; }
command -v gh >/dev/null || { echo "install the GitHub CLI (gh) first" >&2; exit 1; }

[ -d .git ] || git init -b main
if command -v git-lfs >/dev/null; then git lfs install --local; fi
git add -A
if git diff --cached --name-only | grep -qE '(^|/)\.env$'; then
  echo ".env is staged; aborting" >&2; exit 1
fi
if command -v gitleaks >/dev/null; then gitleaks protect --staged --redact; fi
git commit -m "Lanka Link v3"
gh repo create "$name" "$visibility" --source . --push
echo "Set GHCR_OWNER=$(gh api user -q .login) in .env, then watch the release workflow publish the images."
