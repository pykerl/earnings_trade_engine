"""Intraday quote snapshot for the picks tab — the unofficial layer.

One batched 1-minute download for all 13 tickers, latest bar per name,
written to data/picks_intraday.parquet (overwritten every fetch — this is
ephemeral live data, deliberately NOT part of any append-only record).
The official NAV history in picks_nav.parquet remains close-only and
immutable; the dashboard overlays this snapshot only when it is newer than
the last official close, always labeled unofficial.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from common import config
from picks.nav import all_tickers, load_rules

log = logging.getLogger("ete.picks_intraday")

INTRADAY_PARQUET = config.DATA_DIR / "picks_intraday.parquet"


def fetch_snapshot(rules: dict | None = None) -> pd.DataFrame:
    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()
    import yfinance as yf

    rules = rules or load_rules()
    tickers = all_tickers(rules)
    raw = yf.download(tickers, period="1d", interval="1m",
                      auto_adjust=False, progress=False)
    closes = raw["Close"].ffill()
    rows = []
    for t in tickers:
        if t not in closes.columns:
            log.warning("intraday: no bars for %s — tab falls back to last close", t)
            continue
        s = closes[t].dropna()
        if s.empty:
            log.warning("intraday: no bars for %s — tab falls back to last close", t)
            continue
        rows.append({"ticker": t, "last": float(s.iloc[-1]),
                     "asof": s.index[-1].tz_convert("UTC")})
    snap = pd.DataFrame(rows)
    snap["fetched_at"] = datetime.now(timezone.utc)
    config.ensure_dirs()
    snap.to_parquet(INTRADAY_PARQUET, index=False)
    if len(snap):
        log.info("intraday snapshot: %d/%d names as of %s UTC", len(snap), len(tickers),
                 snap["asof"].max().strftime("%H:%M"))
    return snap


if __name__ == "__main__":
    import argparse

    config.setup_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--dashboard", action="store_true",
                    help="rebuild the dashboard after the snapshot")
    args = ap.parse_args()
    fetch_snapshot()
    if args.dashboard:
        from datetime import date

        from dashboard import daily

        daily.run(run_date=date.today())
