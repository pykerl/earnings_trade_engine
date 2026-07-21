.PHONY: setup daily weekly test refresh-all av-backfill picks-postmortem picks-live

# Value engine (plan_value.md §7): ~30 min/week — refresh prices, rescore,
# regenerate memos + the Value tabs, flag new filings on held/watched names.
weekly:
	uv run python run.py weekly

# Reddit-growth engine (plan_reddit_growth step 11): refresh mentions, rescore
# crowding, re-run gates, regenerate ranked ideas + top-8 memos.
ideas:
	uv run python run.py ideas

setup:
	uv sync

# The daily loop (plan §4): refresh chains after close, rescore, update the
# dashboard, append new pre-registration rows. Prices/calendar/history are
# refreshed only when stale (run.py decides); force with refresh-all.
daily:
	uv run python run.py daily

refresh-all:
	uv run python run.py daily --refresh-all

# Season report for the picks race (plan_picks_tab §3). Runnable any time;
# provisional until the end date, FINAL after.
picks-postmortem:
	uv run python -m picks.postmortem

# Refresh the picks tab with live intraday quotes (unofficial overlay; the
# close-only NAV history is never touched) and rebuild the dashboard.
picks-live:
	uv run python -m picks.intraday --dashboard

# Burn today's Alpha Vantage ration on the backfill queue (25 calls/day).
av-backfill:
	uv run python run.py av-backfill

test:
	uv run pytest
