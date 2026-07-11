"""S&P 500 universe + 15yr daily OHLCV -> data/prices.parquet (plan §3 block 1).

Universe comes from the current Wikipedia constituents table (no point-in-time
history needed for a forward test). Prices come from yfinance bulk download in
batches, with per-batch retries; tickers that still fail are logged and
skipped, never fatal.
"""

from __future__ import annotations

import io
import logging
import time
from datetime import date, timedelta

import pandas as pd

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.prices")

WIKI_SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
BATCH_SIZE = 100
BATCH_RETRIES = 3


def _normalize_ticker(symbol: str) -> str:
    """Wikipedia uses BRK.B / BF.B; Yahoo wants BRK-B / BF-B."""
    return symbol.strip().upper().replace(".", "-")


def fetch_sp500_universe(session=None) -> pd.DataFrame:
    """Current S&P 500 members: ticker, name, sector, sub_industry."""
    session = session or make_session()
    resp = get_with_retries(session, WIKI_SP500_URL)
    if resp is None:
        raise RuntimeError("could not fetch S&P 500 constituents from Wikipedia")
    return parse_sp500_html(resp.text)


def parse_sp500_html(html: str) -> pd.DataFrame:
    tables = pd.read_html(io.StringIO(html))
    table = next(t for t in tables if "Symbol" in t.columns and "GICS Sector" in t.columns)
    out = pd.DataFrame(
        {
            "ticker": table["Symbol"].map(_normalize_ticker),
            "name": table["Security"].astype(str),
            "sector": table["GICS Sector"].astype(str),
            "sub_industry": table["GICS Sub-Industry"].astype(str),
        }
    )
    out = out.drop_duplicates("ticker").reset_index(drop=True)
    if len(out) < 400:  # sanity: the table should have ~503 rows
        raise RuntimeError(f"S&P 500 table looks wrong: only {len(out)} rows parsed")
    return out


def _download_batch(tickers: list[str], start: date) -> pd.DataFrame | None:
    import yfinance as yf

    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()

    for attempt in range(BATCH_RETRIES):
        try:
            raw = yf.download(
                tickers=tickers,
                start=start.isoformat(),
                interval="1d",
                auto_adjust=False,
                actions=False,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if raw is not None and not raw.empty:
                return raw
            log.warning("batch of %d returned empty (attempt %d)", len(tickers), attempt + 1)
        except Exception as exc:  # yfinance raises all sorts; skip-and-log per plan
            log.warning("batch download failed: %s (attempt %d)", exc, attempt + 1)
        time.sleep(2 * (attempt + 1))
    return None


def wide_to_long(raw: pd.DataFrame, tickers: list[str]) -> pd.DataFrame:
    """yfinance group_by='ticker' wide frame -> long (ticker, date, ohlcv)."""
    frames = []
    single = not isinstance(raw.columns, pd.MultiIndex)
    for t in tickers:
        try:
            sub = raw if single else raw[t]
        except KeyError:
            log.warning("no data returned for %s; skipping", t)
            continue
        sub = sub.dropna(subset=["Close"])
        if sub.empty:
            log.warning("empty history for %s; skipping", t)
            continue
        frames.append(
            pd.DataFrame(
                {
                    "ticker": t,
                    "date": pd.to_datetime(sub.index).tz_localize(None).normalize(),
                    "open": sub["Open"].to_numpy(dtype=float),
                    "high": sub["High"].to_numpy(dtype=float),
                    "low": sub["Low"].to_numpy(dtype=float),
                    "close": sub["Close"].to_numpy(dtype=float),
                    "adj_close": sub.get("Adj Close", sub["Close"]).to_numpy(dtype=float),
                    "volume": sub["Volume"].fillna(0).to_numpy(dtype="int64"),
                }
            )
        )
    if not frames:
        return pd.DataFrame(
            columns=["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
        )
    return pd.concat(frames, ignore_index=True).sort_values(["ticker", "date"]).reset_index(drop=True)


def download_prices(tickers: list[str], years: int = config.HISTORY_YEARS) -> pd.DataFrame:
    start = date.today() - timedelta(days=int(years * 365.25))
    parts = []
    for i in range(0, len(tickers), BATCH_SIZE):
        batch = tickers[i : i + BATCH_SIZE]
        log.info("downloading OHLCV batch %d-%d of %d", i + 1, i + len(batch), len(tickers))
        raw = _download_batch(batch, start)
        if raw is None:
            log.error("batch %d-%d failed after retries; skipping %d tickers", i + 1, i + len(batch), len(batch))
            continue
        parts.append(wide_to_long(raw, batch))
    if not parts:
        raise RuntimeError("all price batches failed — no OHLCV data")
    prices = pd.concat(parts, ignore_index=True)
    got = prices["ticker"].nunique()
    log.info("downloaded %d rows for %d/%d tickers", len(prices), got, len(tickers))
    return prices


def run() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch universe + prices, persist both, return (universe, prices)."""
    config.ensure_dirs()
    universe = fetch_sp500_universe()
    universe.to_parquet(config.UNIVERSE_PARQUET, index=False)
    log.info("universe: %d names -> %s", len(universe), config.UNIVERSE_PARQUET)

    prices = download_prices(universe["ticker"].tolist())
    prices.to_parquet(config.PRICES_PARQUET, index=False)
    log.info("prices -> %s", config.PRICES_PARQUET)
    return universe, prices


if __name__ == "__main__":
    config.setup_logging()
    run()
