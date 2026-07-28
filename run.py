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

    def _events_empty() -> bool:
        # a failed run can leave a fresh-mtime but EMPTY events file behind;
        # freshness means nothing if there is nothing in it
        try:
            import pandas as pd

            return pd.read_parquet(config.EVENTS_PARQUET).empty
        except Exception:
            return True

    if refresh_all or _stale(config.EVENTS_PARQUET, CALENDAR_MAX_AGE_HOURS) or _events_empty():
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

    if not args.fixtures:  # picks race: real quotes only, and never fatal to the run
        try:
            from picks import enrich as picks_enrich
            from picks import events as picks_events
            from picks import nav as picks_nav

            picks_nav.run()
            picks_events.run(today=today)
            picks_enrich.run()

            from picks import intraday as picks_intraday

            picks_intraday.fetch_snapshot()
        except Exception as exc:
            log.warning("picks pipeline failed (non-fatal, tab shows last data): %s", exc)

    banner = FIXTURE_BANNER if args.fixtures else ""
    html_path, csv_path = dashboard_daily.run(
        scored=scored, run_date=today, banner=banner, plan=plan, squeeze=squeeze
    )

    pred_path = (config.DATA_DIR / "demo" / "predictions_demo.csv") if args.fixtures else None
    new_rows = predictions.register(scored, today=today, path=pred_path)

    if not args.fixtures and config.PREDICTIONS_CSV.exists():
        from scoring import score_log

        try:
            score_log.run(today=today)
            html_path, csv_path = dashboard_daily.run(
                scored=scored, run_date=today, banner=banner, plan=plan, squeeze=squeeze
            )  # rebuild so the Scorecard tab carries today's resolutions
        except Exception as exc:
            log.warning("scorecard refresh failed (non-fatal): %s", exc)

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


def cmd_weekly(args) -> int:
    """Value engine cadence (plan_value.md §7): refresh prices, rescore,
    regenerate memos/dashboard, flag new filings on held/watched names."""
    import pandas as pd

    from dashboard import daily as dashboard_daily
    from features import disqualifiers, quality
    from ingest import gurus as gurus_mod
    from ingest import insiders as insiders_mod
    from ingest import prices as prices_mod
    from ingest import universe as universe_mod
    from journal import writer as journal_writer
    from memos import generator as memo_gen
    from valuation import lenses

    today = date.fromisoformat(args.today) if args.today else date.today()
    config.ensure_dirs()

    if args.refresh_all or not config.VALUE_UNIVERSE_PARQUET.exists():
        universe_mod.run()
        from ingest import edgar_facts

        edgar_facts.run()
    if args.refresh_all or _stale(config.VALUE_PRICES_PARQUET, 6 * 24):
        prices_mod.run_value()
    else:
        log.info("value prices fresh; skipping (use --refresh-all)")

    quality.run()
    disqualifiers.run()
    vals = lenses.run()
    gurus = gurus_mod.run()

    top = vals[vals["rank_score"] > 0].head(15)
    insiders = insiders_mod.run(top["ticker"].tolist(), today=today)

    universe = pd.read_parquet(config.VALUE_UNIVERSE_PARQUET)
    events = (
        pd.read_parquet(config.EVENTS_PARQUET) if config.EVENTS_PARQUET.exists() else None
    )
    memo_paths = memo_gen.generate_memos(
        vals, universe, insiders, gurus, events, top_n=15, memo_date=today
    )
    journal_rows = [
        journal_writer.expectations_row(row, memo_gen.thesis_driver(row), today)
        for _, row in top.iterrows()
    ]
    n_journal = journal_writer.register(journal_rows)

    alerts = new_filing_alerts(vals, universe)
    html_path, _ = dashboard_daily.run(run_date=today)

    print(
        f"\nweekly run complete:\n"
        f"  companies valued : {len(vals)}\n"
        f"  buy candidates   : {int((vals['verdict'] == 'buy candidate').sum())}\n"
        f"  watch list       : {int((vals['verdict'] == 'watch (needs price)').sum())}\n"
        f"  memos drafted    : {len(memo_paths)} -> memos/\n"
        f"  journal rows     : {n_journal} new -> {config.JOURNAL_CSV}\n"
        f"  filing alerts    : {len(alerts)}"
        + ("".join(f"\n    - {a}" for a in alerts) if alerts else "")
        + f"\n  dashboard        : {html_path}"
    )
    return 0


def new_filing_alerts(vals, universe, days: int = 7) -> list[str]:
    """Held/watched names with a fresh 10-K/10-Q/8-K in the last `days`."""
    import json as _json
    from datetime import timedelta

    watched = set(
        vals[vals["verdict"].isin(["buy candidate", "watch (needs price)"])]["ticker"]
    )
    cik_by_ticker = dict(zip(universe["ticker"], universe["cik"]))
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    alerts = []
    for t in sorted(watched):
        cache = config.EDGAR_DIR / "submissions" / f"CIK{int(cik_by_ticker.get(t, 0)):010d}.json"
        if not cache.exists():
            continue
        try:
            recent = _json.loads(cache.read_text())["filings"]["recent"]
        except (ValueError, KeyError):
            continue
        for form, filed in zip(recent.get("form", []), recent.get("filingDate", [])):
            if filed >= cutoff and str(form) in ("10-K", "10-Q", "8-K"):
                alerts.append(f"{t}: {form} filed {filed} — review against the thesis journal")
    return alerts


def cmd_ideas(args) -> int:
    """Reddit-growth engine (plan_reddit_growth step 11): refresh mentions,
    rescore crowding, re-run gates, regenerate ideas dashboard + top-8 memos."""
    import pandas as pd

    from dashboard import daily as dashboard_daily
    from gates import growth_gates
    from ingest import mentions as mentions_mod
    from journal import writer as journal_writer
    from memos import growth_memos
    from positions import construct

    today = date.fromisoformat(args.today) if args.today else date.today()
    config.ensure_dirs()

    mentions_mod.run(today=today)
    gates = growth_gates.run(today=today)
    ideas = construct.run()

    events = (
        pd.read_parquet(config.EVENTS_PARQUET) if config.EVENTS_PARQUET.exists() else None
    )
    memo_paths = growth_memos.generate(ideas, events, top_n=8, memo_date=today)
    rows = [
        journal_writer.growth_expectations_row(
            idea, growth_memos.exit_triggers(
                growth_gates.load_constraint_map()[idea["node"]], idea
            ), today,
        )
        for _, idea in ideas.head(8).iterrows()
    ]
    n_journal = journal_writer.register(
        rows, path=config.REPO_ROOT / "journal" / "growth_expectations.csv",
        fields=journal_writer.GROWTH_FIELDS,
    )
    html_path, _ = dashboard_daily.run(run_date=today)
    print(
        f"\nideas run complete:\n"
        f"  candidates gated : {len(gates)} ({int(gates['gates_passed'].sum())} pass)\n"
        f"  quiet-equity ideas: {len(ideas)}\n"
        f"  options sleeve    : exported -> data/options_sleeve.csv\n"
        f"  memos             : {len(memo_paths)} -> memos/\n"
        f"  journal rows      : {n_journal} new\n"
        f"  dashboard         : {html_path}"
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

    p_weekly = sub.add_parser("weekly", help="value engine: refresh, rescore, memos, dashboard")
    p_weekly.add_argument("--refresh-all", action="store_true",
                          help="re-pull universe + companyfacts + prices")
    p_weekly.add_argument("--today", help="override run date (YYYY-MM-DD)")
    p_weekly.set_defaults(func=cmd_weekly)

    p_ideas = sub.add_parser("ideas", help="reddit-growth engine: mentions, gates, ideas, memos")
    p_ideas.add_argument("--today", help="override run date (YYYY-MM-DD)")
    p_ideas.set_defaults(func=cmd_ideas)

    p_av = sub.add_parser("av-backfill", help="spend today's Alpha Vantage ration on the queue")
    p_av.set_defaults(func=cmd_av_backfill)

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
