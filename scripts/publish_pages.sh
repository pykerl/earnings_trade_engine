#!/usr/bin/env bash
# Publish the latest dashboard to the gh-pages branch (GitHub Pages).
# Site: https://pykerl.github.io/earnings_trade_engine/
#
# Copies the newest data/dashboard/daily_*.html to index.html, keeps the
# dated HTML/CSV alongside it, and refreshes predictions.csv. Idempotent:
# no changes -> no commit, no push.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

LATEST_HTML=$(ls -t data/dashboard/daily_*.html 2>/dev/null | head -1 || true)
if [ -z "$LATEST_HTML" ]; then
    echo "publish_pages: no dashboard found under data/dashboard/; run 'make daily' first" >&2
    exit 1
fi
LATEST_CSV="${LATEST_HTML%.html}.csv"

# make sure we have the remote branch if it exists; create an orphan otherwise
git fetch origin gh-pages >/dev/null 2>&1 || true
if git show-ref --quiet refs/remotes/origin/gh-pages; then
    git branch -f gh-pages origin/gh-pages
elif ! git show-ref --quiet refs/heads/gh-pages; then
    EMPTY_TREE=$(git hash-object -t tree /dev/null)
    git branch gh-pages "$(git commit-tree "$EMPTY_TREE" -m "init gh-pages")"
fi

WT=$(mktemp -d)
cleanup() { git worktree remove --force "$WT" >/dev/null 2>&1 || true; }
trap cleanup EXIT
git worktree add "$WT" gh-pages >/dev/null

cp "$LATEST_HTML" "$WT/index.html"
cp "$LATEST_HTML" "$WT/"
[ -f "$LATEST_CSV" ] && cp "$LATEST_CSV" "$WT/"
[ -f "${LATEST_HTML%.html}_plan.csv" ] && cp "${LATEST_HTML%.html}_plan.csv" "$WT/"
[ -f log/predictions.csv ] && cp log/predictions.csv "$WT/"
[ -f log/squeeze_predictions.csv ] && cp log/squeeze_predictions.csv "$WT/"
touch "$WT/.nojekyll"

cd "$WT"
git add -A
if git diff --cached --quiet; then
    echo "publish_pages: site already up to date"
    exit 0
fi
git commit -q -m "Publish dashboard $(date +%F)"
git push origin gh-pages
echo "publish_pages: published $(basename "$LATEST_HTML") -> gh-pages"
