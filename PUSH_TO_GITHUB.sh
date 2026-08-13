#!/usr/bin/env bash
# One-shot push of AlphaRisk IQ to GitHub.
#
#   cd ~/BASE/02-projects/AlphaRiskIQ && ./PUSH_TO_GITHUB.sh
#
# The repository at $REMOTE already exists and is empty, so this only needs to
# init, commit, wire up the remote and push. No GitHub CLI required.
#
# The test suite and the frontend build run FIRST and the script aborts on
# failure, because a public repo whose tests are red has told a visitor
# something about you within ten seconds of them cloning it.

set -euo pipefail
cd "$(dirname "$0")"

GITHUB_USER="IshaanS0112"
REPO_NAME="AlphaRisk-IQ"
REMOTE="https://github.com/$GITHUB_USER/$REPO_NAME.git"

COMMIT_MESSAGE="AlphaRisk IQ: Sharpe/Sortino under both downside-deviation conventions, historical and parametric VaR with expected shortfall, Kupiec-tested out-of-sample VaR backtesting, beta-adjusted stress scenarios derived from cited index levels, and LLM narration over a frozen structured context"

echo "==> Backend test suite"
if [ -x backend/.venv/bin/python ]; then
    backend/.venv/bin/python -m pytest -q --rootdir=backend backend/tests
else
    echo "    No backend/.venv found. Run ./dev.sh first." >&2
    exit 1
fi

echo "==> Frontend typecheck and build"
(cd frontend && npm install --silent && npm run typecheck && npm run build >/dev/null)

echo "==> Committing"
[ -d .git ] || git init -b main
git add -A

# Last line of defence. .gitignore covers all of these, but a secret pushed to a
# public repo cannot be un-pushed - the blob stays in the history and the key has
# to be treated as compromised. Cheaper to check twice.
if git diff --cached --name-only | grep -qE '(^|/)\.env$|\.db$|__pycache__|\.venv/|node_modules/'; then
    echo "    REFUSING TO COMMIT: something ignored got staged ->" >&2
    git diff --cached --name-only | grep -E '(^|/)\.env$|\.db$|__pycache__|\.venv/|node_modules/' >&2
    exit 1
fi

git commit -m "$COMMIT_MESSAGE"

echo "==> Pushing to $REMOTE"
git remote add origin "$REMOTE" 2>/dev/null || git remote set-url origin "$REMOTE"
git push -u origin main

cat <<MSG

Done -> https://github.com/$GITHUB_USER/$REPO_NAME

Next, on the repo page:
  1. Actions tab - wait for four green ticks. That is the highest-value thing
     on the page: a stranger's machine ran your 156 tests and they passed.
  2. Gear icon next to "About" - paste the description and add the topics.
  3. Add the CI badge to the README (see docs/PUSHING.md).
  4. Pin it to your profile.

MSG
