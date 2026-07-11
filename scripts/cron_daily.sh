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
# If your cron lacks CRON_TZ support, convert 16:30 ET to your local time.

set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."

if [ -f .env ]; then
    set -a
    # shellcheck disable=SC1091
    . ./.env
    set +a
fi

mkdir -p data/logs
LOG="data/logs/daily_$(date +%F).log"
echo "=== run started $(date -Is) ===" >> "$LOG"

uv run python run.py daily >> "$LOG" 2>&1

# Append-only experiment record: commit new pre-registration rows if any.
if [ "${ETE_GIT_PUSH_LOG:-1}" = "1" ]; then
    if ! git diff --quiet -- log/predictions.csv || [ -n "$(git status --porcelain log/predictions.csv)" ]; then
        git add log/predictions.csv
        git commit -m "Pre-register events ($(date +%F))" >> "$LOG" 2>&1
        git push >> "$LOG" 2>&1 || echo "git push failed (will retry next run)" >> "$LOG"
    fi
fi

echo "=== run finished $(date -Is) ===" >> "$LOG"
