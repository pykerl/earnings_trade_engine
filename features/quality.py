"""Quality / moat metric layer (plan_value.md §2).

Input: the tidy annual fundamentals table from ingest/edgar_facts.py.
Output: one row per company with the moat footprints, balance-sheet
survivability, capital-allocation record, and owner earnings.

Owner earnings uses the maintenance-capex proxy min(D&A, capex) — stated as
an explicit field (`maint_capex_proxy`) so every memo can disclose it.
SBC is deliberately NOT added back: it is a real cost to owners.

Sanity harness (mandatory before the layer is declared done):
    uv run python -m features.quality --sanity
prints the 10-year metric table for AAPL, KO, COST, JNJ, ADBE to eyeball
against reality.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.quality")

SANITY_NAMES = ["AAPL", "KO", "COST", "JNJ", "ADBE"]

MAINT_CAPEX_PROXY = "min(depreciation & amortization, capex)"


# ------------------------------------------------------------ per-year math --
def derive_series(annual: pd.DataFrame) -> pd.DataFrame:
    """Add derived per-year columns to one company's FY rows (sorted)."""
    df = annual.sort_values("period_end").reset_index(drop=True).copy()

    if "gross_profit" not in df or df["gross_profit"].isna().all():
        df["gross_profit"] = df["revenue"] - df.get("cost_of_revenue", np.nan)
    df["gross_margin"] = df["gross_profit"] / df["revenue"]
    df["op_margin"] = df["operating_income"] / df["revenue"]

    df["fcf"] = df["cfo"] - df["capex"]
    tax_rate = (df.get("tax_expense", np.nan) / df.get("pretax_income", np.nan)).clip(0, 0.45)
    df["tax_rate"] = tax_rate.fillna(0.21)
    df["nopat"] = df["operating_income"] * (1 - df["tax_rate"])

    debt = df.get("lt_debt", pd.Series(np.nan, index=df.index)).fillna(0) + df.get(
        "st_debt", pd.Series(np.nan, index=df.index)
    ).fillna(0)
    debt[df.get("lt_debt", pd.Series(np.nan, index=df.index)).isna()
         & df.get("st_debt", pd.Series(np.nan, index=df.index)).isna()] = np.nan
    df["total_debt"] = debt
    df["net_debt"] = df["total_debt"].fillna(0) - df["cash"].fillna(0)
    df["invested_capital"] = df["net_debt"] + df["equity"]
    df["roic"] = np.where(df["invested_capital"] > 0, df["nopat"] / df["invested_capital"], np.nan)

    df["ebitda"] = df["operating_income"] + df["dna"].fillna(0)
    df["nd_ebitda"] = np.where(df["ebitda"] > 0, df["net_debt"] / df["ebitda"], np.nan)

    df["maint_capex"] = np.minimum(df["dna"].fillna(df["capex"]), df["capex"])
    df["owner_earnings"] = df["net_income"] + df["dna"].fillna(0) - df["maint_capex"]
    return df


def _cagr(series: pd.Series, years: int) -> float:
    s = series.dropna()
    if len(s) < 2:
        return np.nan
    s = s.tail(years + 1)
    first, last, n = s.iloc[0], s.iloc[-1], len(s) - 1
    if first <= 0 or last <= 0 or n == 0:
        return np.nan
    return (last / first) ** (1 / n) - 1


def _trend(series: pd.Series) -> float:
    """OLS slope per year over available points."""
    s = series.dropna()
    if len(s) < 4:
        return np.nan
    return float(np.polyfit(np.arange(len(s)), s.to_numpy(dtype=float), 1)[0])


def _buyback_timing(df: pd.DataFrame, year_caps: dict[int, float] | None) -> float:
    """Share of buyback dollars spent in cheap years minus expensive years.

    Cheap = that year's market-cap / owner-earnings below the company's own
    median. Needs a per-year market cap; NaN when price history is missing.
    """
    if not year_caps:
        return np.nan
    d = df.dropna(subset=["buybacks", "owner_earnings"])
    d = d[d["owner_earnings"] > 0]
    d = d.assign(year=pd.to_datetime(d["period_end"]).dt.year)
    d["cap"] = d["year"].map(year_caps)
    d = d.dropna(subset=["cap"])
    if len(d) < 4 or d["buybacks"].sum() <= 0:
        return np.nan
    d["multiple"] = d["cap"] / d["owner_earnings"]
    if d["multiple"].nunique() < 2:
        return np.nan
    cheap = d["multiple"] <= d["multiple"].median()
    total = d["buybacks"].sum()
    return float(d.loc[cheap, "buybacks"].sum() / total - d.loc[~cheap, "buybacks"].sum() / total)


# ------------------------------------------------------------ per-company ----
def summarize_company(
    annual: pd.DataFrame, year_caps: dict[int, float] | None = None
) -> dict | None:
    df = derive_series(annual)
    if len(df) < 4:
        return None
    last = df.iloc[-1]
    ten = df.tail(11)

    ni_sum = ten["net_income"].sum()
    fcf_ni = ten["fcf"].sum() / ni_sum if ni_sum > 0 else np.nan

    # incremental ROIC over ~5 years: ΔNOPAT / Δinvested capital
    inc_roic = np.nan
    if len(df) >= 6:
        d_nopat = df["nopat"].iloc[-1] - df["nopat"].iloc[-6]
        d_ic = df["invested_capital"].iloc[-1] - df["invested_capital"].iloc[-6]
        if d_ic > 0:
            inc_roic = d_nopat / d_ic

    growth_years = ten["revenue"].pct_change().dropna()
    rev_2020 = np.nan
    years = pd.to_datetime(df["period_end"]).dt.year
    if 2020 in set(years) and 2019 in set(years):
        r20 = df.loc[years == 2020, "revenue"].iloc[0]
        r19 = df.loc[years == 2019, "revenue"].iloc[0]
        rev_2020 = r20 / r19 - 1 if r19 else np.nan

    interest = last.get("interest_expense", np.nan)
    coverage = last["operating_income"] / interest if interest and interest > 0 else np.nan

    # coarse Altman Z'' (book variant: no market cap needed) as a trap filter
    ta = last["assets"]
    wc = (last.get("current_assets", np.nan) or np.nan) - (last.get("current_liabilities", np.nan) or np.nan)
    z = np.nan
    if ta and ta > 0 and np.isfinite(last.get("liabilities", np.nan)) and last["liabilities"] > 0:
        z = (
            6.56 * (wc / ta if np.isfinite(wc) else 0)
            + 3.26 * ((last.get("retained_earnings", 0) or 0) / ta)
            + 6.72 * (last["operating_income"] / ta)
            + 1.05 * (last["equity"] / last["liabilities"])
        )

    sbc_sum, fcf_sum = ten["sbc"].sum(), ten["fcf"].sum()
    roic_10 = ten["roic"].dropna()

    return {
        "ticker": last["ticker"],
        "years_of_data": len(df),
        "latest_fy_end": last["period_end"],
        # moat footprints
        "roic_median_10y": float(roic_10.median()) if len(roic_10) else np.nan,
        "roic_latest": float(last["roic"]) if np.isfinite(last["roic"]) else np.nan,
        "roic_trend": _trend(ten["roic"]),
        "gross_margin": float(last["gross_margin"]),
        "gm_sigma_10y": float(ten["gross_margin"].std(ddof=1)),
        "gm_trend": _trend(ten["gross_margin"]),
        "op_margin": float(last["op_margin"]),
        "om_sigma_10y": float(ten["op_margin"].std(ddof=1)),
        "fcf_ni_10y": float(fcf_ni) if np.isfinite(fcf_ni) else np.nan,
        "incremental_roic_5y": float(inc_roic) if np.isfinite(inc_roic) else np.nan,
        "rev_cagr_10y": _cagr(df["revenue"], 10),
        "rev_cagr_5y": _cagr(df["revenue"], 5),
        "rev_consistency": float((growth_years > 0).mean()) if len(growth_years) else np.nan,
        "rev_drawdown_2020": rev_2020,
        # survivability
        "nd_ebitda": float(last["nd_ebitda"]) if np.isfinite(last["nd_ebitda"]) else np.nan,
        "interest_coverage": float(coverage) if np.isfinite(coverage) else np.nan,
        "altman_z_coarse": float(z) if np.isfinite(z) else np.nan,
        # management / capital allocation
        "share_cagr_10y": _cagr(df["shares_diluted"], 10),
        "sbc_fcf_10y": float(sbc_sum / fcf_sum) if fcf_sum > 0 else np.nan,
        "buyback_timing": _buyback_timing(df, year_caps),
        "dividend_years_10y": int((df["dividends_paid"].tail(10) > 0).sum()),
        "buyback_years_10y": int((df["buybacks"].tail(10) > 0).sum()),
        # owner earnings (latest year, with the proxy stated)
        "owner_earnings": float(last["owner_earnings"]),
        "owner_earnings_3y_avg": float(df["owner_earnings"].tail(3).mean()),
        "maint_capex_proxy": MAINT_CAPEX_PROXY,
        # moat flag per §2
        "moat_flag": bool(
            len(roic_10)
            and roic_10.median() >= config.MOAT_ROIC_MIN
            and (not np.isfinite(last["nd_ebitda"]) or last["nd_ebitda"] <= config.MOAT_ND_EBITDA_MAX)
        ),
    }


def build_quality(
    fundamentals: pd.DataFrame, year_caps_by_ticker: dict[str, dict[int, float]] | None = None
) -> pd.DataFrame:
    annual = fundamentals[fundamentals["period_type"] == "FY"]
    rows = []
    for ticker, g in annual.groupby("ticker"):
        caps = (year_caps_by_ticker or {}).get(ticker)
        row = summarize_company(g, year_caps=caps)
        if row:
            rows.append(row)
    out = pd.DataFrame(rows)
    log.info("quality metrics for %d companies", len(out))
    return out


def year_caps_from_prices(prices: pd.DataFrame, shares_by_ticker: pd.DataFrame) -> dict:
    """Approximate per-year market cap = yearly average close x latest-known
    diluted shares for that fiscal year (close enough for timing buckets)."""
    caps: dict[str, dict[int, float]] = {}
    shares = shares_by_ticker.copy()
    shares["year"] = pd.to_datetime(shares["period_end"]).dt.year
    share_map = {
        (r.ticker, r.year): r.shares_diluted
        for r in shares.itertuples(index=False)
        if np.isfinite(r.shares_diluted)
    }
    px = prices.assign(year=pd.to_datetime(prices["date"]).dt.year)
    for (ticker, year), g in px.groupby(["ticker", "year"]):
        sh = share_map.get((ticker, year))
        if sh:
            caps.setdefault(ticker, {})[year] = float(g["close"].mean() * sh)
    return caps


def run(fundamentals: pd.DataFrame | None = None, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if fundamentals is None:
        fundamentals = pd.read_parquet(config.FUNDAMENTALS_PARQUET)
    year_caps = None
    if prices is None and config.VALUE_PRICES_PARQUET.exists():
        prices = pd.read_parquet(config.VALUE_PRICES_PARQUET)
    if prices is not None and len(prices):
        annual = fundamentals[fundamentals["period_type"] == "FY"]
        year_caps = year_caps_from_prices(prices, annual[["ticker", "period_end", "shares_diluted"]])
    quality = build_quality(fundamentals, year_caps)
    quality.to_parquet(config.QUALITY_PARQUET, index=False)
    log.info("quality -> %s", config.QUALITY_PARQUET)
    return quality


# ------------------------------------------------------------ sanity harness -
def sanity_table(fundamentals: pd.DataFrame, tickers: list[str] = None) -> None:
    tickers = tickers or SANITY_NAMES
    for t in tickers:
        g = fundamentals[(fundamentals["ticker"] == t) & (fundamentals["period_type"] == "FY")]
        if g.empty:
            print(f"\n=== {t}: NOT IN FUNDAMENTALS (check drops log) ===")
            continue
        df = derive_series(g)
        view = pd.DataFrame(
            {
                "fy_end": df["period_end"],
                "revenue_B": df["revenue"] / 1e9,
                "gm%": 100 * df["gross_margin"],
                "om%": 100 * df["op_margin"],
                "roic%": 100 * df["roic"],
                "fcf_B": df["fcf"] / 1e9,
                "oe_B": df["owner_earnings"] / 1e9,
                "shares_B": df["shares_diluted"] / 1e9,
                "nd/ebitda": df["nd_ebitda"],
            }
        ).tail(11)
        print(f"\n=== {t} — eyeball against the actual 10-Ks ===")
        with pd.option_context("display.float_format", "{:0.2f}".format, "display.width", 200):
            print(view.to_string(index=False))


if __name__ == "__main__":
    import sys

    config.setup_logging()
    if "--sanity" in sys.argv:
        sanity_table(pd.read_parquet(config.FUNDAMENTALS_PARQUET))
    else:
        run()
