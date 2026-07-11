#!/usr/bin/env bash
# Daily EOD run for cron: load .env, run the pipeline (which also FTPS-uploads
# the dashboard when ETE_UPLOAD_* is set), keep a dated log, and push the
# updated pre-registration log so the experiment record lives in git.
#
# Install (4:30pm New York, weekdays):
#   crontab -e
#   CRON_TZ=America/New_York
#   30 16 * * 1-5  /path/to/earnings_trade_engine/scripts/cron_daily.sh
#
# macOS/BSD cron has no CRON_TZ — schedule in your Mac's local time instead
# (e.g. 13:30 for Pacific, 16:30 if your Mac is on Eastern).

set -euo pipefail
# portable repo-root resolution (macOS's BSD readlink lacks -f on older versions)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR/.."

# cron runs with a bare PATH; make sure uv (and Homebrew tools) are findable
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

mkdir -p data/logs
LOG="data/logs/daily_$(date +%F).log"
echo "=== run started $(date "+%Y-%m-%dT%H:%M:%S%z") ===" >> "$LOG"

uv run python run.py daily >> "$LOG" 2>&1

# Publish to GitHub Pages unless explicitly disabled.
if [ "${ETE_PUBLISH_PAGES:-1}" = "1" ]; then
    ./scripts/publish_pages.sh >> "$LOG" 2>&1 || echo "pages publish failed" >> "$LOG"
fi

# Append-only experiment record: commit new pre-registration rows if any.
if [ "${ETE_GIT_PUSH_LOG:-1}" = "1" ]; then
    if ! git diff --quiet -- log/predictions.csv || [ -n "$(git status --porcelain log/predictions.csv)" ]; then
        git add log/predictions.csv
        git commit -m "Pre-register events ($(date +%F))" >> "$LOG" 2>&1
        git push >> "$LOG" 2>&1 || echo "git push failed (will retry next run)" >> "$LOG"
    fi
fi

echo "=== run finished $(date "+%Y-%m-%dT%H:%M:%S%z") ===" >> "$LOG"
