"""Next-21-day earnings calendar, cross-validated (plan §3 block 1).

Primary source: yfinance per-ticker earnings dates (timestamp hour gives a
BMO/AMC hint). Cross-check: Nasdaq's calendar API (keyless) and, when a
FINNHUB_API_KEY is set, Finnhub's free calendar. Per plan §2: names whose
date conflicts across sources are dropped; BMO/AMC disagreements degrade the
session to "unknown". Names seen by only one source are kept but flagged
`single_source` (lower confidence downstream).

Output: data/events_upcoming.parquet
  ticker, earnings_date, session (BMO/AMC/unknown), source_agreement
  (confirmed/single_source), sources, name, sector, cap_b
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import pandas as pd

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.calendar")

NASDAQ_URL = "https://api.nasdaq.com/api/calendar/earnings"
FINNHUB_URL = "https://finnhub.io/api/v1/calendar/earnings"

BMO, AMC, UNKNOWN = "BMO", "AMC", "unknown"


# ---------------------------------------------------------------- yfinance --
def _session_from_hour(ts: pd.Timestamp) -> str:
    """Yahoo earnings timestamps carry a time-of-day in exchange tz."""
    if ts.hour < 10:
        return BMO
    if ts.hour >= 15:
        return AMC
    return UNKNOWN


def _yf_next_event(ticker: str, today: date, horizon: date) -> dict | None:
    import yfinance as yf

    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=8)
    except Exception as exc:
        log.debug("yfinance earnings dates failed for %s: %s", ticker, exc)
        return None
    if df is None or df.empty:
        return None
    future = df.index[(df.index.date >= today) & (df.index.date <= horizon)]
    if len(future) == 0:
        return None
    ts = future.min()  # nearest upcoming
    return {"ticker": ticker, "earnings_date": ts.date(), "session": _session_from_hour(ts)}


def fetch_yfinance_calendar(tickers: list[str], today: date | None = None) -> pd.DataFrame:
    today = today or date.today()
    horizon = today + timedelta(days=config.CALENDAR_DAYS_AHEAD)
    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {pool.submit(_yf_next_event, t, today, horizon): t for t in tickers}
        for fut in as_completed(futures):
            try:
                row = fut.result()
            except Exception as exc:  # belt and braces: never let one name kill the run
                log.warning("yfinance calendar worker failed for %s: %s", futures[fut], exc)
                continue
            if row:
                rows.append(row)
    log.info("yfinance calendar: %d of %d names report by %s", len(rows), len(tickers), horizon)
    return pd.DataFrame(rows, columns=["ticker", "earnings_date", "session"])


# ------------------------------------------------------------------ nasdaq --
def _nasdaq_session(time_field: str) -> str:
    return {"time-pre-market": BMO, "time-after-hours": AMC}.get(time_field, UNKNOWN)


def fetch_nasdaq_calendar(today: date | None = None, session=None) -> pd.DataFrame:
    today = today or date.today()
    session = session or make_session()
    rows = []
    for offset in range(config.CALENDAR_DAYS_AHEAD + 1):
        day = today + timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        resp = get_with_retries(session, NASDAQ_URL, params={"date": day.isoformat()}, retries=2)
        if resp is None:
            continue
        try:
            payload = resp.json()
            for row in (payload.get("data") or {}).get("rows") or []:
                rows.append(
                    {
                        "ticker": str(row.get("symbol", "")).upper().replace(".", "-"),
                        "earnings_date": day,
                        "session": _nasdaq_session(str(row.get("time", ""))),
                    }
                )
        except (ValueError, KeyError, TypeError) as exc:
            log.warning("nasdaq calendar parse failed for %s: %s", day, exc)
    log.info("nasdaq calendar: %d rows", len(rows))
    return pd.DataFrame(rows, columns=["ticker", "earnings_date", "session"])


# ----------------------------------------------------------------- finnhub --
def fetch_finnhub_calendar(today: date | None = None, session=None) -> pd.DataFrame:
    """Optional third source; returns empty frame when no key is configured."""
    key = os.environ.get("FINNHUB_API_KEY")
    cols = ["ticker", "earnings_date", "session"]
    if not key:
        log.info("FINNHUB_API_KEY not set; skipping Finnhub cross-check")
        return pd.DataFrame(columns=cols)
    today = today or date.today()
    session = session or make_session()
    resp = get_with_retries(
        session,
        FINNHUB_URL,
        params={
            "from": today.isoformat(),
            "to": (today + timedelta(days=config.CALENDAR_DAYS_AHEAD)).isoformat(),
            "token": key,
        },
    )
    if resp is None:
        return pd.DataFrame(columns=cols)
    rows = []
    try:
        for row in resp.json().get("earningsCalendar", []):
            rows.append(
                {
                    "ticker": str(row.get("symbol", "")).upper().replace(".", "-"),
                    "earnings_date": date.fromisoformat(row["date"]),
                    "session": {"bmo": BMO, "amc": AMC}.get(row.get("hour", ""), UNKNOWN),
                }
            )
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("finnhub calendar parse failed: %s", exc)
    log.info("finnhub calendar: %d rows", len(rows))
    return pd.DataFrame(rows, columns=cols)


# --------------------------------------------------------------- reconcile --
def reconcile(
    yf_events: pd.DataFrame,
    cross_sources: dict[str, pd.DataFrame],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Cross-validate yfinance events against secondary calendars.

    Rules (plan §2): a name whose yfinance date conflicts with any secondary
    source that also lists it is DROPPED. A name confirmed by >=1 source is
    `confirmed`; a name no secondary source lists is kept as `single_source`.
    Sessions: unanimous non-unknown wins; any disagreement -> unknown.
    """
    kept, dropped = [], []
    lookups = {
        name: df.set_index("ticker") if not df.empty else pd.DataFrame()
        for name, df in cross_sources.items()
    }
    for row in yf_events.itertuples(index=False):
        agree, conflict = [], []
        sessions = [row.session]
        for name, lk in lookups.items():
            if lk.empty or row.ticker not in lk.index:
                continue
            entry = lk.loc[row.ticker]
            if isinstance(entry, pd.DataFrame):  # source listed the ticker twice
                entry = entry.iloc[0]
            if entry["earnings_date"] == row.earnings_date:
                agree.append(name)
                sessions.append(entry["session"])
            else:
                conflict.append(f"{name}={entry['earnings_date']}")
        if conflict:
            dropped.append(
                {"ticker": row.ticker, "yf_date": row.earnings_date, "conflicts": "; ".join(conflict)}
            )
            continue
        known = {s for s in sessions if s != UNKNOWN}
        session = known.pop() if len(known) == 1 else UNKNOWN
        kept.append(
            {
                "ticker": row.ticker,
                "earnings_date": row.earnings_date,
                "session": session,
                "source_agreement": "confirmed" if agree else "single_source",
                "sources": ",".join(["yfinance", *agree]),
            }
        )
    kept_df = pd.DataFrame(
        kept, columns=["ticker", "earnings_date", "session", "source_agreement", "sources"]
    )
    dropped_df = pd.DataFrame(dropped, columns=["ticker", "yf_date", "conflicts"])
    if len(dropped_df):
        log.warning("dropped %d names on cross-source date conflicts: %s",
                    len(dropped_df), ", ".join(dropped_df["ticker"]))
    return kept_df, dropped_df


# ------------------------------------------------------------- market caps --
def fetch_market_caps(tickers: list[str]) -> pd.Series:
    """Market cap in $B via yfinance fast_info; NaN on failure (per-ticker)."""
    import yfinance as yf

    def one(t: str) -> tuple[str, float]:
        try:
            cap = yf.Ticker(t).fast_info["marketCap"]
            return t, float(cap) / 1e9 if cap else float("nan")
        except Exception as exc:
            log.debug("market cap failed for %s: %s", t, exc)
            return t, float("nan")

    with ThreadPoolExecutor(max_workers=8) as pool:
        pairs = list(pool.map(one, tickers))
    return pd.Series(dict(pairs), name="cap_b")


def run(universe: pd.DataFrame | None = None, today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if universe is None:
        universe = pd.read_parquet(config.UNIVERSE_PARQUET)
    sp500 = set(universe["ticker"])

    yf_events = fetch_yfinance_calendar(sorted(sp500), today=today)
    cross = {
        "nasdaq": fetch_nasdaq_calendar(today=today),
        "finnhub": fetch_finnhub_calendar(today=today),
    }
    events, dropped = reconcile(yf_events, cross)
    events = events[events["ticker"].isin(sp500)].reset_index(drop=True)

    caps = fetch_market_caps(events["ticker"].tolist()) if len(events) else pd.Series(dtype=float)
    events = events.merge(universe[["ticker", "name", "sector"]], on="ticker", how="left")
    events["cap_b"] = events["ticker"].map(caps)

    events.to_parquet(config.EVENTS_PARQUET, index=False)
    log.info(
        "events: %d kept (%d confirmed, %d single-source), %d dropped -> %s",
        len(events),
        (events["source_agreement"] == "confirmed").sum() if len(events) else 0,
        (events["source_agreement"] == "single_source").sum() if len(events) else 0,
        len(dropped),
        config.EVENTS_PARQUET,
    )
    return events


if __name__ == "__main__":
    config.setup_logging()
    run()
