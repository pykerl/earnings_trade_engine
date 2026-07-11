"""Ownership / float / short-interest data per upcoming reporter (tabs 2-3).

"Main St vs Wall St" in measurable form, free sources only:
  * yfinance `info`  — float, shares outstanding, institutional %, insider %,
    shares short, short % of float, days-to-cover, average volume.
  * Nasdaq's short-interest API — official bi-monthly settlements for
    Nasdaq-LISTED names only; used to cross-check Yahoo and to compute the
    short-interest TREND (latest vs prior settlement). NYSE names keep the
    Yahoo numbers (FINRA's CDN would cover them but needs a network-policy
    allowlist entry for cdn.finra.org).

Derived: retail_pct = 1 - institutional - insider (a proxy — nobody
publishes true retail ownership), float_turnover = avg daily volume / float
(how fast the whole float changes hands: the "can it move fast" number).

Missing fields degrade to NaN, never crash the run.

Output: data/positioning.parquet
"""

from __future__ import annotations

import logging
import math
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import pandas as pd

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.positioning")

NASDAQ_SI_URL = "https://api.nasdaq.com/api/quote/{ticker}/short-interest"

POSITIONING_COLUMNS = [
    "ticker", "float_shares", "shares_outstanding", "inst_pct", "insider_pct",
    "retail_pct", "si_shares", "si_pct_float", "days_to_cover", "avg_vol_10d",
    "float_turnover", "si_trend", "si_source",
]


def _num(value) -> float:
    try:
        v = float(value)
        return v if math.isfinite(v) else float("nan")
    except (TypeError, ValueError):
        return float("nan")


# ---------------------------------------------------------------- yfinance --
def fetch_yf_positioning(ticker: str) -> dict:
    """One name's ownership/short snapshot from Yahoo; NaNs on any failure."""
    import yfinance as yf

    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()
    row = {c: float("nan") for c in POSITIONING_COLUMNS if c not in ("ticker", "si_source")}
    row["ticker"] = ticker
    row["si_source"] = "none"
    try:
        info = yf.Ticker(ticker).info or {}
    except Exception as exc:
        log.warning("positioning fetch failed for %s: %s (skipping)", ticker, exc)
        return row
    row["float_shares"] = _num(info.get("floatShares"))
    row["shares_outstanding"] = _num(info.get("sharesOutstanding"))
    row["inst_pct"] = _num(info.get("heldPercentInstitutions"))
    row["insider_pct"] = _num(info.get("heldPercentInsiders"))
    row["si_shares"] = _num(info.get("sharesShort"))
    row["si_pct_float"] = _num(info.get("shortPercentOfFloat"))
    row["days_to_cover"] = _num(info.get("shortRatio"))
    row["avg_vol_10d"] = _num(info.get("averageDailyVolume10Day") or info.get("averageVolume"))
    if np.isfinite(row["si_pct_float"]) and row["si_pct_float"] > 0:
        row["si_source"] = "yahoo"
    return row


# ------------------------------------------------------------------ nasdaq --
def parse_nasdaq_si(payload: dict) -> dict | None:
    """Latest + prior official settlement -> shares short, DTC, trend."""
    try:
        rows = payload["data"]["shortInterestTable"]["rows"]
    except (KeyError, TypeError):
        return None
    if not rows:
        return None

    def shares(r) -> float:
        return _num(str(r.get("interest", "")).replace(",", ""))

    latest = rows[0]
    out = {
        "si_shares": shares(latest),
        "days_to_cover": _num(latest.get("daysToCover")),
        "si_trend": float("nan"),
    }
    if len(rows) > 1 and shares(rows[1]) > 0:
        out["si_trend"] = out["si_shares"] / shares(rows[1]) - 1.0
    return out if np.isfinite(out["si_shares"]) and out["si_shares"] > 0 else None


def fetch_nasdaq_si(ticker: str, session) -> dict | None:
    resp = get_with_retries(
        session, NASDAQ_SI_URL.format(ticker=ticker), params={"assetClass": "stocks"}, retries=2
    )
    if resp is None:
        return None
    try:
        return parse_nasdaq_si(resp.json())
    except ValueError:
        return None


# --------------------------------------------------------------------- run --
def build_positioning(tickers: list[str], nasdaq_session=None) -> pd.DataFrame:
    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(fetch_yf_positioning, tickers))
    df = pd.DataFrame(rows)

    session = nasdaq_session or make_session()
    hits = 0
    for i, ticker in enumerate(df["ticker"]):
        official = fetch_nasdaq_si(ticker, session)
        if official is None:
            continue  # NYSE-listed or no data: keep Yahoo numbers
        hits += 1
        df.loc[i, "si_shares"] = official["si_shares"]
        if np.isfinite(official["days_to_cover"]):
            df.loc[i, "days_to_cover"] = official["days_to_cover"]
        df.loc[i, "si_trend"] = official["si_trend"]
        if np.isfinite(df.loc[i, "float_shares"]) and df.loc[i, "float_shares"] > 0:
            df.loc[i, "si_pct_float"] = official["si_shares"] / df.loc[i, "float_shares"]
        df.loc[i, "si_source"] = "nasdaq"
    log.info("positioning: %d names (%d with official Nasdaq SI)", len(df), hits)

    df["retail_pct"] = (1.0 - df["inst_pct"].fillna(0) - df["insider_pct"].fillna(0)).clip(0, 1)
    df.loc[df["inst_pct"].isna(), "retail_pct"] = float("nan")
    df["float_turnover"] = df["avg_vol_10d"] / df["float_shares"]
    return df[POSITIONING_COLUMNS]


def run(events: pd.DataFrame | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if events is None:
        events = pd.read_parquet(config.EVENTS_PARQUET)
    df = build_positioning(events["ticker"].tolist())
    df.to_parquet(config.POSITIONING_PARQUET, index=False)
    log.info("positioning -> %s", config.POSITIONING_PARQUET)
    return df


if __name__ == "__main__":
    config.setup_logging()
    run()
