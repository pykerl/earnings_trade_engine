import numpy as np
import pandas as pd
import pytest

from features import quality


def _annual(ticker="TST", years=10, rev0=1000.0, growth=0.07):
    rows = []
    for i in range(years + 1):
        rev = rev0 * (1 + growth) ** i
        rows.append(
            {
                "ticker": ticker, "period_type": "FY",
                "period_end": f"{2015 + i}-12-31",
                "revenue": rev,
                "cost_of_revenue": rev * 0.40,
                "gross_profit": rev * 0.60,
                "operating_income": rev * 0.25,
                "pretax_income": rev * 0.24,
                "tax_expense": rev * 0.24 * 0.20,
                "net_income": rev * 0.19,
                "interest_expense": rev * 0.01,
                "cfo": rev * 0.23,
                "capex": rev * 0.05,
                "dna": rev * 0.04,
                "sbc": rev * 0.02,
                "dividends_paid": rev * 0.05,
                "buybacks": rev * 0.06,
                "shares_diluted": 1_000.0 * (1 - 0.01) ** i,  # 1%/yr shrink
                "cash": rev * 0.30,
                "st_investments": np.nan,
                "lt_debt": rev * 0.20,
                "st_debt": rev * 0.02,
                "equity": rev * 0.50,
                "assets": rev * 1.20,
                "liabilities": rev * 0.70,
                "current_assets": rev * 0.50,
                "current_liabilities": rev * 0.30,
                "retained_earnings": rev * 0.40,
            }
        )
    return pd.DataFrame(rows)


def test_derived_series_math():
    df = quality.derive_series(_annual())
    last = df.iloc[-1]
    assert last["gross_margin"] == pytest.approx(0.60)
    assert last["fcf"] == pytest.approx(last["revenue"] * 0.18)
    # tax rate 20% -> NOPAT = 0.25 * 0.8 = 0.20 rev
    assert last["nopat"] == pytest.approx(last["revenue"] * 0.20)
    # net debt = 0.22 rev - 0.30 rev = -0.08 rev (net cash)
    assert last["net_debt"] == pytest.approx(-0.08 * last["revenue"])
    # ROIC = 0.20 rev / (0.50 - 0.08) rev
    assert last["roic"] == pytest.approx(0.20 / 0.42, rel=1e-3)
    # owner earnings: maint capex = min(dna, capex) = 0.04 rev
    assert last["maint_capex"] == pytest.approx(0.04 * last["revenue"])
    assert last["owner_earnings"] == pytest.approx((0.19 + 0.04 - 0.04) * last["revenue"])


def test_summary_metrics_on_steady_compounder():
    row = quality.summarize_company(_annual())
    assert row["roic_median_10y"] == pytest.approx(0.20 / 0.42, rel=1e-3)
    assert row["moat_flag"], "20%+ ROIC with net cash must set the moat flag"
    assert row["rev_cagr_10y"] == pytest.approx(0.07, abs=1e-3)
    assert row["rev_consistency"] == 1.0
    assert row["share_cagr_10y"] == pytest.approx(-0.01, abs=1e-3)
    assert row["gm_sigma_10y"] == pytest.approx(0.0, abs=1e-9)
    assert row["fcf_ni_10y"] == pytest.approx(0.18 / 0.19, rel=1e-3)
    assert row["sbc_fcf_10y"] == pytest.approx(0.02 / 0.18, rel=1e-3)
    assert row["dividend_years_10y"] == 10
    assert row["interest_coverage"] == pytest.approx(25.0)
    assert row["maint_capex_proxy"] == quality.MAINT_CAPEX_PROXY
    assert np.isfinite(row["altman_z_coarse"]) and row["altman_z_coarse"] > 3


def test_moat_flag_denied_on_leverage():
    df = _annual()
    df["lt_debt"] = df["revenue"] * 1.2       # ND/EBITDA blows past 2.5
    df["cash"] = 0.0
    row = quality.summarize_company(df)
    assert row["nd_ebitda"] > 2.5
    assert not row["moat_flag"]


def test_buyback_timing_rewards_cheap_year_purchases():
    df = quality.derive_series(_annual())
    years = pd.to_datetime(df["period_end"]).dt.year
    oe = df["owner_earnings"]
    caps = {}
    buybacks = {}
    for i, y in enumerate(years):
        cheap = i % 2 == 0
        caps[int(y)] = float(oe.iloc[i] * (10 if cheap else 30))
        buybacks[int(y)] = 100.0 if cheap else 0.0  # only buys in cheap years
    df["buybacks"] = [buybacks[int(y)] for y in years]
    score = quality._buyback_timing(df, caps)
    assert score == pytest.approx(1.0)
    df["buybacks"] = [100.0 - buybacks[int(y)] for y in years]  # only expensive years
    assert quality._buyback_timing(df, caps) == pytest.approx(-1.0)


def test_short_history_returns_none():
    assert quality.summarize_company(_annual(years=2)) is None


def test_build_quality_multi_company():
    fund = pd.concat([_annual("AAA"), _annual("BBB", growth=0.02)], ignore_index=True)
    out = quality.build_quality(fund)
    assert set(out["ticker"]) == {"AAA", "BBB"}
    aaa = out.set_index("ticker").loc["AAA"]
    bbb = out.set_index("ticker").loc["BBB"]
    assert aaa["rev_cagr_10y"] > bbb["rev_cagr_10y"]
