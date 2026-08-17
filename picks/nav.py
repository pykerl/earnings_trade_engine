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
INCEPTION_CSV = config.LOG_DIR / "picks_inception.csv"  # committed record (data/ is gitignored)
NAV_PARQUET = config.DATA_DIR / "picks_nav.parquet"
POSITIONS_PARQUET = config.DATA_DIR / "picks_positions.parquet"
ACTIONS_CSV = config.DATA_DIR / "picks_actions.csv"

NAV_TOL = 0.01          # re-derivation noise we don't even mention
RESTATEMENT_TOL = 1.00  # vendor restatements up to $1 of NAV: log + keep frozen rows


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


BIG_MOVE = 0.10          # daily move that triggers the second-source cross-check
CROSS_CHECK_TOL = 0.02   # max Yahoo-vs-Nasdaq disagreement before we refuse


def _nasdaq_close(ticker: str, day) -> float | None:
    """Independent close from the Nasdaq API; None when unavailable."""
    from common.http import get_with_retries, make_session

    try:
        resp = get_with_retries(
            make_session(),
            f"https://api.nasdaq.com/api/quote/{ticker}/chart",
            params={"assetclass": "stocks", "fromdate": day.isoformat(),
                    "todate": day.isoformat()},
            retries=2,
        )
        points = (resp.json().get("data") or {}).get("chart") or []
        return float(points[-1]["z"]["value"]) if points else None
    except Exception as exc:
        log.warning("nasdaq cross-check unavailable for %s: %s", ticker, exc)
        return None


def validate_last_closes(closes: pd.DataFrame) -> None:
    """Cross-check big single-day moves before they can freeze into NAV.

    Yahoo has twice served a phantom QBTS close (~-22% day moves that never
    happened) that poisoned frozen rows at first write, where the append-only
    guard cannot help. Any name moving more than BIG_MOVE day-over-day gets
    its close verified against the Nasdaq API; disagreement beyond
    CROSS_CHECK_TOL aborts the run rather than writing a fiction."""
    if len(closes) < 2:
        return
    last, prev = closes.iloc[-1], closes.iloc[-2]
    day = closes.index[-1].date()
    for t in closes.columns:
        if not (np.isfinite(last[t]) and np.isfinite(prev[t]) and prev[t] > 0):
            continue
        if abs(last[t] / prev[t] - 1.0) <= BIG_MOVE:
            continue
        ref = _nasdaq_close(t, day)
        if ref is None:
            log.warning("%s moved %+.1f%% and Nasdaq cross-check unavailable — proceeding "
                        "on Yahoo alone", t, 100 * (last[t] / prev[t] - 1))
            continue
        if abs(float(last[t]) / ref - 1.0) > CROSS_CHECK_TOL:
            raise RuntimeError(
                f"{t} close {last[t]:.2f} disagrees with Nasdaq {ref:.2f} on {day} "
                f"after a >{BIG_MOVE:.0%} move — refusing to freeze a suspect print"
            )
        log.info("%s big move cross-checked ok (yahoo %.2f vs nasdaq %.2f)", t, last[t], ref)


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
    if not INCEPTION_PARQUET.exists() and INCEPTION_CSV.exists():
        # fresh container: data/ is ephemeral, the committed CSV is the record
        pd.read_csv(INCEPTION_CSV).to_parquet(INCEPTION_PARQUET, index=False)
        log.info("inception restored from committed %s", INCEPTION_CSV)
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
    if not INCEPTION_CSV.exists():  # the durable copy is first-write-only too
        INCEPTION_CSV.parent.mkdir(parents=True, exist_ok=True)
        fresh.to_csv(INCEPTION_CSV, index=False)
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
    """First write wins, forever: stored rows are the official record and are
    never replaced — recomputation only appends genuinely new (date, portfolio)
    rows. Free-data vendors restate old closes by pennies (LULU's 2026-07-30
    close moved a fraction of a cent the next day); that gets logged and the
    frozen row kept. Drift beyond RESTATEMENT_TOL means something is actually
    wrong (bad split handling, wrong ticker data) and still hard-fails."""
    if not NAV_PARQUET.exists():
        nav.to_parquet(NAV_PARQUET, index=False)
        return nav
    prior = pd.read_parquet(NAV_PARQUET)
    merged = prior.merge(nav, on=["date", "portfolio"], suffixes=("_old", "_new"), how="inner")
    if len(merged):
        drift = float((merged["nav_old"] - merged["nav_new"]).abs().max())
        assert drift <= RESTATEMENT_TOL, (
            f"historical NAV re-derives ${drift:.2f} different — beyond any plausible "
            "vendor restatement; refusing to write (check splits/dividends/ticker data)"
        )
        if drift > NAV_TOL:
            log.warning(
                "vendor restated history (NAV re-derives up to $%.2f different) — "
                "frozen rows kept as first written", drift,
            )
    prior_keys = set(zip(prior["date"], prior["portfolio"]))
    new_rows = nav[[(d, p) not in prior_keys
                    for d, p in zip(nav["date"], nav["portfolio"])]]
    out = (
        pd.concat([prior, new_rows], ignore_index=True)
        .sort_values(["portfolio", "date"]).reset_index(drop=True)
    )
    out.to_parquet(NAV_PARQUET, index=False)
    return out


def _run_once(rules: dict) -> pd.DataFrame:
    closes, dividends, splits = fetch_market_data(rules)
    validate_last_closes(closes)
    inception = load_or_freeze_inception(rules, closes)
    positions = compute_positions(inception, closes, dividends, splits)
    positions.to_parquet(POSITIONS_PARQUET, index=False)
    return append_only_write(compute_nav(positions))


def run() -> pd.DataFrame:
    import time

    config.ensure_dirs()
    rules = load_rules()
    try:
        nav = _run_once(rules)
    except (AssertionError, RuntimeError) as exc:
        # Yahoo's feed intermittently returns corrupt history mid-download
        # (three incidents in two weeks); one clean refetch usually clears it,
        # and every guard re-runs on the retry
        log.warning("picks NAV rejected a suspect fetch (%s) — retrying once in 30s", exc)
        time.sleep(30)
        nav = _run_once(rules)
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
