"""Historical earnings dates per upcoming reporter + AV backfill (plan §3 block 1).

Fast path: yfinance `get_earnings_dates` for every name on the upcoming
calendar (limited depth, but free and instant). Names with a thin history
(< MIN_HISTORY_QUARTERS past events) go on a persistent Alpha Vantage
backfill queue, prioritized by "reporting within 10 days" (plan §2).

The AV drip treats calls as the scarcest resource: 25/day and one call per
12.5s, enforced by a persistent limiter (data/av_state.json) that survives
restarts. The API key comes from $ALPHAVANTAGE_API_KEY only — never
hardcoded; with no key the drip is a logged no-op.

Output: data/earnings_history.parquet
  ticker, event_date, session (BMO/AMC/unknown), eps_estimate, reported_eps,
  surprise_pct, source (yfinance/alphavantage)
"""

from __future__ import annotations

import json
import logging
import os
import time as _time
from datetime import date, datetime, timedelta

import pandas as pd

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.earnings_history")

AV_URL = "https://www.alphavantage.co/query"

HISTORY_COLUMNS = [
    "ticker", "event_date", "session", "eps_estimate", "reported_eps",
    "surprise_pct", "source",
]


# ---------------------------------------------------------------- yfinance --
def _session_from_hour(hour: int) -> str:
    if hour < 10:
        return "BMO"
    if hour >= 15:
        return "AMC"
    return "unknown"


def fetch_yf_history(ticker: str, today: date | None = None, limit: int = 48) -> pd.DataFrame:
    """Past earnings events for one name via yfinance; empty frame on failure."""
    import yfinance as yf

    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()

    today = today or date.today()
    try:
        df = yf.Ticker(ticker).get_earnings_dates(limit=limit)
    except Exception as exc:
        log.warning("yfinance earnings history failed for %s: %s (skipping)", ticker, exc)
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    if df is None or df.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    df = df[df.index.date < today]
    if df.empty:
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    return pd.DataFrame(
        {
            "ticker": ticker,
            "event_date": [ts.date() for ts in df.index],
            "session": [_session_from_hour(ts.hour) for ts in df.index],
            "eps_estimate": pd.to_numeric(df.get("EPS Estimate"), errors="coerce").to_numpy(),
            "reported_eps": pd.to_numeric(df.get("Reported EPS"), errors="coerce").to_numpy(),
            "surprise_pct": pd.to_numeric(df.get("Surprise(%)"), errors="coerce").to_numpy(),
            "source": "yfinance",
        }
    )


def fetch_all_yf_history(tickers: list[str], today: date | None = None) -> pd.DataFrame:
    frames = [fetch_yf_history(t, today=today) for t in tickers]
    out = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=HISTORY_COLUMNS)
    return dedupe_history(out)


def dedupe_history(history: pd.DataFrame) -> pd.DataFrame:
    """One row per (ticker, event_date); prefer rows with a known session,
    then yfinance over AV (yfinance timestamps carry the session hint)."""
    if history.empty:
        return history
    ranked = history.assign(
        _known=(history["session"] != "unknown").astype(int),
        _src=(history["source"] == "yfinance").astype(int),
    ).sort_values(["_known", "_src"], ascending=False)
    out = ranked.drop_duplicates(["ticker", "event_date"]).drop(columns=["_known", "_src"])
    return out.sort_values(["ticker", "event_date"]).reset_index(drop=True)


# ----------------------------------------------------- Alpha Vantage drip ---
class AVRateLimiter:
    """Persistent 25/day + 12.5s-gap limiter (plan §2 rate-limit budget)."""

    def __init__(self, state_path=None, clock=None, sleeper=None):
        self.state_path = state_path or config.AV_STATE_JSON
        self.clock = clock or _time.time
        self.sleeper = sleeper or _time.sleep
        self.state = self._load()

    def _load(self) -> dict:
        try:
            state = json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            state = {}
        today = self._today()
        if state.get("date") != today:
            state = {"date": today, "calls_today": 0, "last_call_ts": 0.0}
        return state

    def _today(self) -> str:
        return datetime.fromtimestamp(self.clock()).date().isoformat()

    def calls_remaining(self) -> int:
        if self.state.get("date") != self._today():  # rolled past midnight mid-run
            self.state = {"date": self._today(), "calls_today": 0, "last_call_ts": 0.0}
        return config.AV_MAX_CALLS_PER_DAY - self.state["calls_today"]

    def acquire(self) -> bool:
        """Block until a call is allowed; False if today's ration is spent."""
        if self.calls_remaining() <= 0:
            return False
        wait = self.state["last_call_ts"] + config.AV_MIN_SECONDS_BETWEEN_CALLS - self.clock()
        if wait > 0:
            self.sleeper(wait)
        self.state["calls_today"] += 1
        self.state["last_call_ts"] = self.clock()
        self._save()
        return True

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.state_path.write_text(json.dumps(self.state))


def build_backfill_queue(
    events: pd.DataFrame, history: pd.DataFrame, today: date | None = None
) -> list[dict]:
    """Names with thin history, nearest reporters first (plan §2 priority 1).

    Queue entries carry a `purpose` so the same drip can later ration
    HISTORICAL_OPTIONS backfill (plan §2 priority 2) without a schema change.
    """
    today = today or date.today()
    counts = history.groupby("ticker").size() if not history.empty else pd.Series(dtype=int)
    queue = []
    for row in events.sort_values("earnings_date").itertuples(index=False):
        n = int(counts.get(row.ticker, 0))
        if n >= config.MIN_HISTORY_QUARTERS:
            continue
        days_out = (row.earnings_date - today).days
        queue.append(
            {
                "ticker": row.ticker,
                "purpose": "earnings_dates",
                "n_have": n,
                "days_to_report": days_out,
                "priority": 0 if days_out <= config.AV_BACKFILL_PRIORITY_DAYS else 1,
            }
        )
    queue.sort(key=lambda q: (q["priority"], q["days_to_report"]))
    config.ensure_dirs()
    config.AV_QUEUE_JSON.write_text(json.dumps(queue, indent=1))
    log.info("AV backfill queue: %d names -> %s", len(queue), config.AV_QUEUE_JSON)
    return queue


def parse_av_earnings(payload: dict, ticker: str) -> pd.DataFrame:
    rows = []
    for q in payload.get("quarterlyEarnings", []):
        reported = q.get("reportedDate")
        if not reported:
            continue
        session = {"pre-market": "BMO", "post-market": "AMC"}.get(
            str(q.get("reportTime", "")).lower(), "unknown"
        )
        def num(key):
            try:
                return float(q.get(key))
            except (TypeError, ValueError):
                return float("nan")
        rows.append(
            {
                "ticker": ticker,
                "event_date": date.fromisoformat(reported),
                "session": session,
                "eps_estimate": num("estimatedEPS"),
                "reported_eps": num("reportedEPS"),
                "surprise_pct": num("surprisePercentage"),
                "source": "alphavantage",
            }
        )
    return pd.DataFrame(rows, columns=HISTORY_COLUMNS)


def run_av_backfill(
    max_calls: int | None = None,
    limiter: AVRateLimiter | None = None,
    session=None,
    api_key: str | None = None,
) -> pd.DataFrame:
    """Drain the queue within today's ration; returns newly fetched rows."""
    api_key = api_key or os.environ.get(config.AV_API_KEY_ENV)
    if not api_key:
        log.info("%s not set — AV backfill skipped (queue preserved)", config.AV_API_KEY_ENV)
        return pd.DataFrame(columns=HISTORY_COLUMNS)
    try:
        queue = json.loads(config.AV_QUEUE_JSON.read_text())
    except (OSError, ValueError):
        log.info("no AV backfill queue on disk; nothing to do")
        return pd.DataFrame(columns=HISTORY_COLUMNS)

    limiter = limiter or AVRateLimiter()
    session = session or make_session()
    budget = limiter.calls_remaining() if max_calls is None else min(max_calls, limiter.calls_remaining())
    log.info("AV backfill: %d queued, %d calls available today", len(queue), budget)

    fetched, remaining = [], list(queue)
    for entry in queue:
        if budget <= 0 or not limiter.acquire():
            break
        budget -= 1
        resp = get_with_retries(
            session, AV_URL,
            params={"function": "EARNINGS", "symbol": entry["ticker"], "apikey": api_key},
            retries=2,
        )
        remaining.remove(entry)
        if resp is None:
            continue
        try:
            payload = resp.json()
        except ValueError:
            log.warning("AV returned non-JSON for %s", entry["ticker"])
            continue
        if "Note" in payload or "Information" in payload:  # rate-limit notices
            log.warning("AV throttle notice for %s: %s", entry["ticker"],
                        payload.get("Note") or payload.get("Information"))
            remaining.append(entry)  # retry another day
            break
        df = parse_av_earnings(payload, entry["ticker"])
        log.info("AV backfill %s: %d historical events", entry["ticker"], len(df))
        fetched.append(df)

    config.AV_QUEUE_JSON.write_text(json.dumps(remaining, indent=1))
    return pd.concat(fetched, ignore_index=True) if fetched else pd.DataFrame(columns=HISTORY_COLUMNS)


# --------------------------------------------------------------------- run --
def run(events: pd.DataFrame | None = None, today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if events is None:
        events = pd.read_parquet(config.EVENTS_PARQUET)

    history = fetch_all_yf_history(events["ticker"].tolist(), today=today)

    # merge any prior history (e.g. earlier AV drips) so depth accumulates
    if config.EARNINGS_HISTORY_PARQUET.exists():
        prior = pd.read_parquet(config.EARNINGS_HISTORY_PARQUET)
        history = dedupe_history(pd.concat([history, prior], ignore_index=True))

    build_backfill_queue(events, history, today=today)
    av_rows = run_av_backfill()
    if not av_rows.empty:
        history = dedupe_history(pd.concat([history, av_rows], ignore_index=True))

    history.to_parquet(config.EARNINGS_HISTORY_PARQUET, index=False)
    log.info(
        "earnings history: %d events across %d names -> %s",
        len(history), history["ticker"].nunique() if len(history) else 0,
        config.EARNINGS_HISTORY_PARQUET,
    )
    return history


if __name__ == "__main__":
    config.setup_logging()
    run()
