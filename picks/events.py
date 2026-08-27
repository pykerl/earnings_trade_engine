"""Earnings-date resolver + T-1 freeze for the picks competition (plan §4.5).

Dates are NEVER hardcoded: every one of the 11 names is resolved live via the
calendar module's sources with the standard two-source cross-check
(yfinance primary; Nasdaq + optional Finnhub secondary; conflicting dates are
flagged, not silently kept). The picks season runs ~7 weeks, past the main
engine's 21-day window, so sources are queried in chunks out to the season
end date.

T-1 freeze, per the standard journal discipline: on the last trading day
before a name reports, one frozen row (implied move from live chains, fair
move from the model when the name is covered) is appended to
log/picks_predictions.csv via the shared first-write-wins journal writer.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd

from common import config
from ingest import calendar as cal
from log import predictions

log = logging.getLogger("ete.picks_events")

PICKS_EVENTS_PARQUET = config.DATA_DIR / "picks_events.parquet"
PICKS_PREDICTIONS_CSV = config.LOG_DIR / "picks_predictions.csv"

FIELDS = [
    "registered_at", "portfolio", "ticker", "earnings_date", "session",
    "expiry", "spot", "atm_strike",
    "straddle_bid", "straddle_mid", "straddle_ask",
    "implied_move_bid", "implied_move_mid", "implied_move_ask",
    "fair_move", "ci_low", "ci_high", "n_events",
    "source_agreement", "sources",
]


def picks_universe(rules: dict) -> pd.DataFrame:
    rows = [
        {"ticker": t, "portfolio": pname}
        for pname, p in rules["portfolios"].items()
        for t in p["tickers"]
    ]
    return pd.DataFrame(rows)


# ----------------------------------------------------------- date resolution --
def _yf_events(tickers: list[str], today: date, horizon: date) -> pd.DataFrame:
    rows = []
    for t in tickers:
        row = cal._yf_next_event(t, today, horizon)
        if row:
            rows.append(row)
    return pd.DataFrame(rows, columns=["ticker", "earnings_date", "session"])


def _nasdaq_events(today: date, horizon: date) -> pd.DataFrame:
    """Nasdaq calendar in 22-day chunks out to the season horizon."""
    frames, chunk = [], today
    step = config.CALENDAR_DAYS_AHEAD + 1
    while chunk <= horizon:
        frames.append(cal.fetch_nasdaq_calendar(today=chunk))
        chunk += timedelta(days=step)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(
        columns=["ticker", "earnings_date", "session"]
    )


def resolve_dates(rules: dict, today: date | None = None) -> pd.DataFrame:
    """One row per pick with a cross-checked date, or a flagged status.

    status: confirmed | single_source | conflict | unresolved. Conflicted and
    unresolved names keep a row (earnings_date=NaT for unresolved) so the tab
    always shows all 11 names — nothing is silently dropped.
    """
    today = today or market_today()
    horizon = date.fromisoformat(rules["rules"]["end_date"]) + timedelta(days=10)
    uni = picks_universe(rules)
    tickers = uni["ticker"].tolist()

    yf_events = _yf_events(tickers, today, horizon)
    cross = {
        "nasdaq": _nasdaq_events(today, horizon),
        "finnhub": cal.fetch_finnhub_calendar(today=today),
    }
    kept, dropped = cal.reconcile(yf_events, cross)

    kept = kept.rename(columns={"source_agreement": "status"})
    conflicts = pd.DataFrame(
        [
            {"ticker": r.ticker, "earnings_date": r.yf_date, "session": cal.UNKNOWN,
             "status": "conflict", "sources": f"yfinance vs {r.conflicts}"}
            for r in dropped.itertuples(index=False)
        ],
        columns=["ticker", "earnings_date", "session", "status", "sources"],
    )
    resolved = pd.concat([kept, conflicts], ignore_index=True)
    events = uni.merge(resolved, on="ticker", how="left")
    events["status"] = events["status"].fillna("unresolved")
    events["session"] = events["session"].fillna(cal.UNKNOWN)
    events["sources"] = events["sources"].fillna("")

    n_dated = events["earnings_date"].notna().sum()
    log.info(
        "picks events: %d/%d dated (%s)", n_dated, len(events),
        ", ".join(f"{r.ticker} {r.earnings_date} [{r.status}]"
                  for r in events.itertuples(index=False)),
    )
    return events


# ---------------------------------------------------------------- T-1 freeze --
def t1_date(earnings_date: date) -> date:
    """Last trading day strictly before the report date."""
    return pd.bdate_range(end=earnings_date - timedelta(days=1), periods=1)[0].date()


def _fair_move_lookup() -> pd.DataFrame:
    if config.FAIR_PARQUET.exists():
        cols = ["ticker", "fair_move", "ci_low", "ci_high", "n_events"]
        fair = pd.read_parquet(config.FAIR_PARQUET)
        return fair[[c for c in cols if c in fair.columns]].drop_duplicates("ticker")
    return pd.DataFrame(columns=["ticker", "fair_move", "ci_low", "ci_high", "n_events"])


def t1_freeze(events: pd.DataFrame, today: date | None = None) -> pd.DataFrame:
    """Freeze journal rows for names at T-1 (chains implied + model fair move).

    Relies on the shared journal's contract: first write wins, and events on
    or before `today` are refused — so a row can only ever be written strictly
    before the print.
    """
    from ingest.chains import fetch_event_chain

    today = today or market_today()
    due = events[
        events["earnings_date"].notna()
        & events["status"].isin(["confirmed", "single_source"])
    ].copy()
    if due.empty:
        return pd.DataFrame(columns=FIELDS)
    due["earnings_date"] = pd.to_datetime(due["earnings_date"]).dt.date
    due = due[(due["earnings_date"] > today)
              & (due["earnings_date"].map(t1_date) <= today)]
    if due.empty:
        log.info("picks T-1 freeze: no names at T-1 today")
        return pd.DataFrame(columns=FIELDS)

    fair = _fair_move_lookup()
    rows = []
    for r in due.itertuples(index=False):
        chain = fetch_event_chain(r.ticker, r.earnings_date, r.session)
        summary = chain[0] if chain else {}
        if not chain:
            log.warning("picks T-1: no usable chain for %s — freezing without implied", r.ticker)
        rows.append({
            "portfolio": r.portfolio, "ticker": r.ticker,
            "earnings_date": r.earnings_date, "session": r.session,
            "status": r.status, "sources": r.sources,
            "source_agreement": r.status, **summary,
        })
    frame = pd.DataFrame(rows).merge(fair, on="ticker", how="left")
    registered = predictions.register(
        frame, today=today, path=PICKS_PREDICTIONS_CSV, fields=FIELDS
    )
    if len(registered):
        log.info("picks T-1 freeze: journaled %s",
                 ", ".join(registered["ticker"].astype(str)))
    return registered


def market_today() -> date:
    """The trading-calendar date. An evening run in New York is next-day UTC,
    which once skipped a T-1 freeze for a next-morning BMO print — 'today'
    here must always mean the market's today."""
    return datetime.now(ZoneInfo("America/New_York")).date()


def run(today: date | None = None) -> pd.DataFrame:
    from picks.nav import load_rules

    today = today or market_today()
    config.ensure_dirs()
    rules = load_rules()
    events = resolve_dates(rules, today=today)
    today_ = today
    # names that already reported drop out of the forward calendars; their
    # dates are history, not unresolved — backfill from the prior record,
    # with the committed journal as the durable fallback (the parquet is an
    # uncommitted cache and dies with the container)
    past = (
        pd.read_parquet(PICKS_EVENTS_PARQUET) if PICKS_EVENTS_PARQUET.exists()
        else pd.DataFrame(columns=["ticker", "portfolio", "earnings_date",
                                   "session", "status", "sources"])
    )
    past = past[past["earnings_date"].notna()].copy()
    if PICKS_PREDICTIONS_CSV.exists():
        j = pd.read_csv(PICKS_PREDICTIONS_CSV)
        j = j.rename(columns={"source_agreement": "status"})[
            ["ticker", "portfolio", "earnings_date", "session", "status", "sources"]
        ]
        past = pd.concat([past, j[~j["ticker"].isin(past["ticker"])]],
                         ignore_index=True)
    if len(past):
        past["earnings_date"] = pd.to_datetime(past["earnings_date"]).dt.date
        past = past[~past.duplicated("ticker", keep="first")].set_index("ticker")
        for i, r in events.iterrows():
            if pd.isna(r["earnings_date"]) and r["ticker"] in past.index:
                p = past.loc[r["ticker"]]
                # a past date is history ("reported"); a FUTURE date carried
                # through a source outage keeps its prior status so the next
                # healthy resolve can still confirm or conflict it — dropping
                # it would silently skip that name's T-1 freeze
                status = "reported" if p["earnings_date"] <= today_ else p["status"]
                events.loc[i, ["earnings_date", "session", "status", "sources"]] = [
                    p["earnings_date"], p["session"], status, p["sources"]]
    if events["earnings_date"].isna().all() and PICKS_EVENTS_PARQUET.exists():
        prior = pd.read_parquet(PICKS_EVENTS_PARQUET)
        if prior["earnings_date"].notna().any():
            # 0/11 resolved when we had dates before = source outage (stale
            # Yahoo cookie), not eleven simultaneously-pulled dates. Keeping
            # the prior file also keeps a due T-1 freeze from being skipped.
            raise RuntimeError(
                "all picks earnings dates unresolved but prior run had dates — "
                "source outage; keeping the previous picks_events.parquet"
            )
    events.to_parquet(PICKS_EVENTS_PARQUET, index=False)
    t1_freeze(events, today=today)
    return events


if __name__ == "__main__":
    config.setup_logging()
    run()
