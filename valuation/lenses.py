"""Four independent valuation lenses + margin of safety (plan_value.md §3).

All lenses run on normalized owner earnings (3-year average — the Buffett
number with the maintenance-capex proxy inherited from features/quality):

  1. owner-earnings yield vs the FRED 10-yr: fair EV = OE / (t10 + spread),
     the "equity bond" framing; equity value = fair EV − net debt.
  2. conservative two-stage DCF: stage-1 growth = min(10-yr revenue CAGR,
     10% hard cap), fading linearly to 2.5% terminal, 10% flat discount;
     the ±2pt growth range is reported alongside.
  3. Greenwald EPV: zero-growth perpetuity OE / discount — what the moat is
     worth if it only defends. Price below EPV means growth is free.
  4. reverse DCF: the growth rate the CURRENT price implies, solved by
     bisection — the memo states it against the historical record.

Margin of safety = discount of market cap to the MOST CONSERVATIVE of
lenses 1–3 (never the average). Buy list ≥ 27%, watch list ≥ 15%.
"""

from __future__ import annotations

import io
import logging

import numpy as np
import pandas as pd

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.lenses")

FRED_DGS10_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
FALLBACK_T10 = 0.045  # used (and logged) only if FRED is unreachable


def fetch_treasury_10y(session=None) -> float:
    session = session or make_session()
    resp = get_with_retries(session, FRED_DGS10_URL)
    if resp is None:
        log.warning("FRED unreachable; using fallback 10yr = %.2f%%", 100 * FALLBACK_T10)
        return FALLBACK_T10
    try:
        df = pd.read_csv(io.StringIO(resp.text))
        vals = pd.to_numeric(df.iloc[:, 1], errors="coerce").dropna()
        return float(vals.iloc[-1]) / 100.0
    except Exception as exc:
        log.warning("FRED parse failed (%s); using fallback", exc)
        return FALLBACK_T10


# ------------------------------------------------------------------ lenses --
def dcf_value(
    oe: float,
    growth: float,
    years: int = config.DCF_STAGE1_YEARS,
    terminal: float = config.DCF_TERMINAL_GROWTH,
    discount: float = config.DCF_DISCOUNT_RATE,
) -> float:
    """Two-stage DCF on owner earnings; growth fades linearly to terminal."""
    if oe <= 0 or not np.isfinite(oe):
        return float("nan")
    pv, cash = 0.0, oe
    for t in range(1, years + 1):
        g = growth + (terminal - growth) * (t - 1) / years  # linear fade
        cash *= 1 + g
        pv += cash / (1 + discount) ** t
    tv = cash * (1 + terminal) / (discount - terminal)
    return pv + tv / (1 + discount) ** years


def epv(oe: float, discount: float = config.DCF_DISCOUNT_RATE) -> float:
    """Greenwald earnings-power value: zero-growth perpetuity."""
    return oe / discount if oe > 0 and np.isfinite(oe) else float("nan")


def oe_yield_value(oe: float, net_debt: float, t10: float) -> float:
    """Fair equity value from the equity-bond framing."""
    if oe <= 0 or not np.isfinite(oe):
        return float("nan")
    fair_ev = oe / (t10 + config.OE_YIELD_MIN_SPREAD)
    return fair_ev - (net_debt if np.isfinite(net_debt) else 0.0)


def reverse_dcf(market_cap: float, oe: float, lo: float = -0.10, hi: float = 0.30) -> float:
    """Growth the current price implies under the same DCF machinery."""
    if oe <= 0 or market_cap <= 0 or not np.isfinite(oe) or not np.isfinite(market_cap):
        return float("nan")
    if dcf_value(oe, lo) > market_cap:
        return lo  # already cheaper than a shrinking business
    if dcf_value(oe, hi) < market_cap:
        return float("nan")  # price implies growth beyond any sane cap
    for _ in range(60):
        mid = (lo + hi) / 2
        if dcf_value(oe, mid) < market_cap:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


# --------------------------------------------------------------- valuation --
def value_company(row: pd.Series, t10: float) -> dict:
    oe = row["owner_earnings_3y_avg"]
    net_debt = row.get("net_debt", np.nan)
    mktcap = row["market_cap"]

    g_hist = row.get("rev_cagr_10y", np.nan)
    growth = min(g_hist, config.DCF_GROWTH_HARD_CAP) if np.isfinite(g_hist) else np.nan
    growth = max(growth, 0.0) if np.isfinite(growth) else np.nan

    v_yield = oe_yield_value(oe, net_debt, t10)
    v_dcf = dcf_value(oe, growth) if np.isfinite(growth) else float("nan")
    v_dcf_lo = dcf_value(oe, max(growth - config.DCF_GROWTH_RANGE_PTS, -0.05)) if np.isfinite(growth) else float("nan")
    v_dcf_hi = dcf_value(oe, min(growth + config.DCF_GROWTH_RANGE_PTS, config.DCF_GROWTH_HARD_CAP)) if np.isfinite(growth) else float("nan")
    v_epv = epv(oe)

    lenses = [v for v in (v_yield, v_dcf, v_epv) if np.isfinite(v) and v > 0]
    conservative = min(lenses) if len(lenses) == 3 else float("nan")
    mos = 1 - mktcap / conservative if np.isfinite(conservative) and conservative > 0 else float("nan")

    return {
        "ticker": row["ticker"],
        "market_cap": mktcap,
        "net_debt": net_debt,
        "owner_earnings_norm": oe,
        "oe_yield": oe / (mktcap + net_debt) if np.isfinite(net_debt) and (mktcap + net_debt) > 0 else np.nan,
        "t10": t10,
        "dcf_growth_used": growth,
        "value_oe_yield": v_yield,
        "value_dcf": v_dcf,
        "value_dcf_low": v_dcf_lo,
        "value_dcf_high": v_dcf_hi,
        "value_epv": v_epv,
        "value_conservative": conservative,
        "implied_growth": reverse_dcf(mktcap, oe),
        "margin_of_safety": mos,
    }


def build_valuations(
    quality: pd.DataFrame,
    fundamentals: pd.DataFrame,
    universe: pd.DataFrame,
    disqualifiers: pd.DataFrame,
    t10: float,
) -> pd.DataFrame:
    annual = fundamentals[fundamentals["period_type"] == "FY"].sort_values("period_end")
    latest = annual.groupby("ticker").tail(1).copy()
    latest["net_debt"] = latest["lt_debt"].fillna(0) + latest["st_debt"].fillna(0) - latest["cash"].fillna(0)

    caps = universe.set_index("ticker")["cap_b"] * 1e9
    merged = quality.merge(latest[["ticker", "net_debt"]], on="ticker", how="left")
    merged["market_cap"] = merged["ticker"].map(caps)
    merged = merged.dropna(subset=["market_cap"])

    rows = [value_company(r, t10) for _, r in merged.iterrows()]
    vals = pd.DataFrame(rows)

    out = vals.merge(quality, on="ticker", how="left").merge(
        disqualifiers, on="ticker", how="left"
    )
    out["eject"] = out["eject"].fillna(False)
    out["demote_count"] = out["demote_count"].fillna(0)

    # rank score: margin of safety, halved per demotion, zeroed on ejection,
    # and gated on the moat flag (quality before cheapness, plan §0)
    out["rank_score"] = np.where(
        out["eject"] | ~out["moat_flag"].fillna(False),
        0.0,
        out["margin_of_safety"].fillna(0) * 0.5 ** out["demote_count"],
    )
    out["verdict"] = np.select(
        [
            out["eject"],
            ~out["moat_flag"].fillna(False),
            out["rank_score"] >= config.MOS_BUY,
            out["rank_score"] >= config.MOS_WATCH,
        ],
        ["ejected", "no moat evidence", "buy candidate", "watch (needs price)"],
        default="pass",
    )
    out = out.sort_values("rank_score", ascending=False).reset_index(drop=True)
    log.info(
        "valuations: %d names, %d buy candidates, %d watch",
        len(out), int((out["verdict"] == "buy candidate").sum()),
        int((out["verdict"] == "watch (needs price)").sum()),
    )
    return out


def run() -> pd.DataFrame:
    config.ensure_dirs()
    quality = pd.read_parquet(config.QUALITY_PARQUET)
    fundamentals = pd.read_parquet(config.FUNDAMENTALS_PARQUET)
    universe = pd.read_parquet(config.VALUE_UNIVERSE_PARQUET)
    disq = pd.read_parquet(config.DISQUALIFIERS_PARQUET)
    t10 = fetch_treasury_10y()
    log.info("10yr treasury: %.2f%%", 100 * t10)
    out = build_valuations(quality, fundamentals, universe, disq, t10)
    out.to_parquet(config.VALUATIONS_PARQUET, index=False)
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
