"""Daily NAV engine for the picks competition (plan_picks_tab §4.2).

Immutability contract:
  * inception rows (entry close, shares) are computed ONCE from the first
    available close on/after the configured date, written to
    data/picks_inception.parquet, and NEVER modified — any run that computes
    different values for an existing inception row raises AssertionError;
  * daily NAV rows are append-only: existing (date, portfolio) rows are
    asserted unchanged (small float tolerance) before new dates append.

Total-return basis: dividends credited as cash on ex-date (uninvested);
splits multiply share counts on the ex-date; every corporate action detected
is logged and recorded in data/picks_actions.csv.

All 11 names + both benchmarks must resolve in yfinance BEFORE any
inception row is written — otherwise the run stops loudly (plan constraint).
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
import yaml

from common import config

log = logging.getLogger("ete.picks_nav")

PICKS_YAML = config.REPO_ROOT / "config" / "picks.yaml"
INCEPTION_PARQUET = config.DATA_DIR / "picks_inception.parquet"
NAV_PARQUET = config.DATA_DIR / "picks_nav.parquet"
POSITIONS_PARQUET = config.DATA_DIR / "picks_positions.parquet"
ACTIONS_CSV = config.DATA_DIR / "picks_actions.csv"

NAV_TOL = 0.01  # a cent of NAV tolerance when re-deriving historical rows


def load_rules(path=PICKS_YAML) -> dict:
    return yaml.safe_load(path.read_text())


def all_tickers(rules: dict) -> list[str]:
    names = [t for p in rules["portfolios"].values() for t in p["tickers"]]
    return sorted(set(names + rules["benchmarks"]))


def fetch_market_data(rules: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """(closes, dividends, splits) wide frames since inception_earliest.

    Raises RuntimeError listing any ticker that fails to resolve — the plan
    says stop and show, never write partial inception rows.
    """
    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()
    import yfinance as yf

    tickers = all_tickers(rules)
    start = rules["rules"]["inception_earliest"]
    raw = yf.download(tickers, start=start, auto_adjust=False, actions=True, progress=False)
    closes = raw["Close"]
    dividends = raw.get("Dividends", pd.DataFrame(0.0, index=closes.index, columns=tickers))
    splits = raw.get("Stock Splits", pd.DataFrame(0.0, index=closes.index, columns=tickers))
    missing = [t for t in tickers if t not in closes.columns or closes[t].dropna().empty]
    if missing:
        raise RuntimeError(
            f"tickers failed to resolve in yfinance: {missing} — refusing to write "
            "inception rows (plan: stop and show)"
        )
    return closes, dividends.fillna(0.0), splits.fillna(0.0)


# --------------------------------------------------------------- inception --
def build_inception(rules: dict, closes: pd.DataFrame) -> pd.DataFrame:
    """Entry price + frozen fractional shares per position (benchmarks incl.)."""
    inception_day = closes.dropna(how="any").index.min()
    rows = []
    for pname, p in rules["portfolios"].items():
        for t in p["tickers"]:
            entry = float(closes.loc[inception_day, t])
            rows.append(
                {
                    "portfolio": pname, "ticker": t,
                    "inception_date": inception_day.date().isoformat(),
                    "entry_close": entry,
                    "allocation": float(p["allocation_per_name"]),
                    "shares": float(p["allocation_per_name"]) / entry,
                }
            )
    for b in rules["benchmarks"]:
        entry = float(closes.loc[inception_day, b])
        rows.append(
            {
                "portfolio": f"BM:{b}", "ticker": b,
                "inception_date": inception_day.date().isoformat(),
                "entry_close": entry,
                "allocation": 10_000.0,
                "shares": 10_000.0 / entry,
            }
        )
    return pd.DataFrame(rows)


def load_or_freeze_inception(rules: dict, closes: pd.DataFrame) -> pd.DataFrame:
    fresh = build_inception(rules, closes)
    if INCEPTION_PARQUET.exists():
        frozen = pd.read_parquet(INCEPTION_PARQUET)
        merged = frozen.merge(fresh, on=["portfolio", "ticker"], suffixes=("_frozen", "_new"))
        assert len(merged) == len(frozen) == len(fresh), (
            "inception universe changed — refusing to proceed"
        )
        same_date = (merged["inception_date_frozen"] == merged["inception_date_new"]).all()
        same_px = np.allclose(merged["entry_close_frozen"], merged["entry_close_new"], rtol=1e-6)
        same_sh = np.allclose(merged["shares_frozen"], merged["shares_new"], rtol=1e-6)
        assert same_date and same_px and same_sh, (
            "attempt to overwrite immutable inception rows detected — inception is "
            "frozen at first write, forever. Delete data/picks_inception.parquet ONLY "
            "if you intend to restart the contest."
        )
        return frozen
    fresh.to_parquet(INCEPTION_PARQUET, index=False)
    log.info(
        "INCEPTION FROZEN at %s close: %d positions written once",
        fresh["inception_date"].iloc[0], len(fresh),
    )
    return fresh


# ------------------------------------------------------------------ NAV -----
def compute_positions(
    inception: pd.DataFrame, closes: pd.DataFrame, dividends: pd.DataFrame, splits: pd.DataFrame
) -> pd.DataFrame:
    """Daily per-position rows: shares (split-adjusted), value, cash from divs."""
    rows = []
    actions = []
    start = pd.Timestamp(inception["inception_date"].iloc[0])
    days = closes.index[closes.index >= start]
    for pos in inception.itertuples(index=False):
        shares = pos.shares
        cash = 0.0
        for d in days:
            split = float(splits.loc[d, pos.ticker]) if pos.ticker in splits.columns else 0.0
            if split and split > 0 and split != 1.0:
                shares *= split
                actions.append({"date": d.date().isoformat(), "ticker": pos.ticker,
                                "action": "split", "ratio": split})
                log.warning("corporate action: %s split %.4g on %s", pos.ticker, split, d.date())
            div = float(dividends.loc[d, pos.ticker]) if pos.ticker in dividends.columns else 0.0
            if div and div > 0:
                cash += shares * div
                actions.append({"date": d.date().isoformat(), "ticker": pos.ticker,
                                "action": "dividend", "ratio": div})
            close = closes.loc[d, pos.ticker]
            if not np.isfinite(close):
                continue
            rows.append(
                {
                    "date": d.date(), "portfolio": pos.portfolio, "ticker": pos.ticker,
                    "shares": shares, "close": float(close),
                    "value": shares * float(close), "cash": cash,
                    "entry_close": pos.entry_close,
                }
            )
    if actions:
        pd.DataFrame(actions).to_csv(ACTIONS_CSV, index=False)
    return pd.DataFrame(rows)


def compute_nav(positions: pd.DataFrame) -> pd.DataFrame:
    nav = (
        positions.groupby(["date", "portfolio"])
        .agg(nav=("value", "sum"), cash=("cash", "sum"))
        .reset_index()
    )
    nav["nav"] = nav["nav"] + nav["cash"]
    return nav.sort_values(["portfolio", "date"]).reset_index(drop=True)


def append_only_write(nav: pd.DataFrame) -> pd.DataFrame:
    """Assert existing rows unchanged (esp. inception), then write the union."""
    if NAV_PARQUET.exists():
        prior = pd.read_parquet(NAV_PARQUET)
        merged = prior.merge(nav, on=["date", "portfolio"], suffixes=("_old", "_new"), how="inner")
        if len(merged):
            drift = (merged["nav_old"] - merged["nav_new"]).abs().max()
            assert drift <= NAV_TOL, (
                f"historical NAV rows changed by ${drift:.2f} — append-only contract "
                "violated (bad price restatement?); refusing to overwrite"
            )
    nav.to_parquet(NAV_PARQUET, index=False)
    return nav


def run() -> pd.DataFrame:
    config.ensure_dirs()
    rules = load_rules()
    closes, dividends, splits = fetch_market_data(rules)
    inception = load_or_freeze_inception(rules, closes)
    positions = compute_positions(inception, closes, dividends, splits)
    positions.to_parquet(POSITIONS_PARQUET, index=False)
    nav = append_only_write(compute_nav(positions))
    latest = nav[nav["date"] == nav["date"].max()]
    log.info(
        "picks NAV through %s: %s",
        nav["date"].max(),
        " · ".join(f"{r.portfolio} ${r.nav:,.0f}" for r in latest.itertuples(index=False)),
    )
    return nav


if __name__ == "__main__":
    config.setup_logging()
    run()
