.PHONY: setup daily weekly test refresh-all av-backfill

# Value engine (plan_value.md §7): ~30 min/week — refresh prices, rescore,
# regenerate memos + the Value tabs, flag new filings on held/watched names.
weekly:
	uv run python run.py weekly

setup:
	uv sync

# The daily loop (plan §4): refresh chains after close, rescore, update the
# dashboard, append new pre-registration rows. Prices/calendar/history are
# refreshed only when stale (run.py decides); force with refresh-all.
daily:
	uv run python run.py daily

refresh-all:
	uv run python run.py daily --refresh-all

# Burn today's Alpha Vantage ration on the backfill queue (25 calls/day).
av-backfill:
	uv run python run.py av-backfill

test:
	uv run pytest
