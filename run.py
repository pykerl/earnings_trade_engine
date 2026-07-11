"""Single entrypoint for the daily loop (plan §4: ~15 min/day).

    uv run python run.py daily              # or: make daily
    uv run python run.py daily --refresh-all
    uv run python run.py daily --fixtures   # offline demo on synthetic data
    uv run python run.py av-backfill        # burn today's AV ration only

`daily` refreshes chains, rescores, rewrites the dashboard, and appends new
pre-registration rows. Slow inputs are refreshed only when stale: prices
after PRICES_MAX_AGE_DAYS, calendar/history after CALENDAR_MAX_AGE_HOURS.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import date
from pathlib import Path

from common import config

log = logging.getLogger("ete.run")

PRICES_MAX_AGE_DAYS = 3
CALENDAR_MAX_AGE_HOURS = 20

FIXTURE_BANNER = "SYNTHETIC DATA — OFFLINE DEMO. Not market data; do not trade or interpret."


def _stale(path: Path, max_age_hours: float) -> bool:
    if not path.exists():
        return True
    return (time.time() - path.stat().st_mtime) > max_age_hours * 3600


def ingest_real(today: date, refresh_all: bool) -> None:
    from ingest import calendar as cal
    from ingest import chains, earnings_history, positioning, prices

    if refresh_all or _stale(config.PRICES_PARQUET, PRICES_MAX_AGE_DAYS * 24):
        prices.run()
    else:
        log.info("prices fresh (< %dd); skipping (use --refresh-all to force)", PRICES_MAX_AGE_DAYS)

    if refresh_all or _stale(config.EVENTS_PARQUET, CALENDAR_MAX_AGE_HOURS):
        cal.run(today=today)
        earnings_history.run(today=today)
    else:
        log.info("calendar fresh (< %dh); skipping", CALENDAR_MAX_AGE_HOURS)

    if refresh_all or _stale(config.POSITIONING_PARQUET, CALENDAR_MAX_AGE_HOURS):
        positioning.run()
    else:
        log.info("positioning fresh (< %dh); skipping", CALENDAR_MAX_AGE_HOURS)

    chains.run(today=today)  # always refreshed: this is the daily signal


def cmd_daily(args) -> int:
    from dashboard import daily as dashboard_daily
    from features import moves
    from log import predictions
    from model import fair_move
    from scoring import rank

    today = date.fromisoformat(args.today) if args.today else date.today()
    config.ensure_dirs()

    if args.fixtures:
        from common import fixtures

        log.warning(FIXTURE_BANNER)
        fixtures.generate_all(today)
    else:
        ingest_real(today, args.refresh_all)

    moves.run()
    fair_move.run()
    scored = rank.run()

    from scoring import squeeze as squeeze_mod
    from scoring.size import build_trade_plan

    squeeze = squeeze_mod.run(today=today)
    plan = build_trade_plan(scored, today=today)

    banner = FIXTURE_BANNER if args.fixtures else ""
    html_path, csv_path = dashboard_daily.run(
        scored=scored, run_date=today, banner=banner, plan=plan, squeeze=squeeze
    )

    pred_path = (config.DATA_DIR / "demo" / "predictions_demo.csv") if args.fixtures else None
    new_rows = predictions.register(scored, today=today, path=pred_path)

    sq_candidates = squeeze[squeeze["candidate"]] if len(squeeze) else squeeze
    sq_path = (
        (config.DATA_DIR / "demo" / "squeeze_predictions_demo.csv")
        if args.fixtures
        else config.SQUEEZE_PREDICTIONS_CSV
    )
    new_sq = predictions.register(
        sq_candidates, today=today, path=sq_path, fields=predictions.SQUEEZE_FIELDS
    ) if len(sq_candidates) else sq_candidates

    published = False
    if not args.fixtures:  # never publish synthetic output
        from dashboard import publish

        if publish.configured():
            published = publish.publish_dashboard(html_path, csv_path, config.PREDICTIONS_CSV)

    n_live = int((~scored["screened"]).sum()) if len(scored) else 0
    print(
        f"\ndaily run complete ({'FIXTURES' if args.fixtures else 'live data'}):\n"
        f"  events scored : {len(scored)} ({n_live} pass liquidity screen)\n"
        f"  trade plan    : {len(plan)} positions, "
        f"${plan['position_risk'].sum() if len(plan) else 0:,.0f} at risk\n"
        f"  squeeze watch : {int(squeeze['candidate'].sum()) if len(squeeze) else 0} candidates "
        f"({len(new_sq)} newly pre-registered)\n"
        f"  dashboard     : {html_path}\n"
        f"  csv           : {csv_path}\n"
        f"  new pre-regs  : {len(new_rows)} -> "
        f"{pred_path or config.PREDICTIONS_CSV}\n"
        f"  published     : {'yes' if published else 'no (set ETE_UPLOAD_* to enable)'}"
    )
    return 0


def cmd_av_backfill(_args) -> int:
    from ingest.earnings_history import run_av_backfill

    fetched = run_av_backfill()
    if not fetched.empty:
        import pandas as pd

        from ingest.earnings_history import dedupe_history

        prior = (
            pd.read_parquet(config.EARNINGS_HISTORY_PARQUET)
            if config.EARNINGS_HISTORY_PARQUET.exists()
            else fetched.iloc[0:0]
        )
        merged = dedupe_history(pd.concat([prior, fetched], ignore_index=True))
        merged.to_parquet(config.EARNINGS_HISTORY_PARQUET, index=False)
        log.info("merged %d backfilled events into history", len(fetched))
    return 0


def main(argv=None) -> int:
    config.setup_logging()
    parser = argparse.ArgumentParser(description="earnings trade engine v1")
    sub = parser.add_subparsers(dest="cmd")

    p_daily = sub.add_parser("daily", help="refresh chains, rescore, dashboard, pre-register")
    p_daily.add_argument("--refresh-all", action="store_true", help="force-refresh prices/calendar")
    p_daily.add_argument("--fixtures", action="store_true", help="offline demo on synthetic data")
    p_daily.add_argument("--today", help="override run date (YYYY-MM-DD), mainly for fixtures")
    p_daily.set_defaults(func=cmd_daily)

    p_av = sub.add_parser("av-backfill", help="spend today's Alpha Vantage ration on the queue")
    p_av.set_defaults(func=cmd_av_backfill)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
