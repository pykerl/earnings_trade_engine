import numpy as np
import pandas as pd
import pytest

from common import config
from valuation import lenses


def test_epv_is_zero_growth_perpetuity():
    assert lenses.epv(100.0) == pytest.approx(1000.0)  # 100 / 0.10
    assert np.isnan(lenses.epv(-5.0))


def test_dcf_zero_growth_approaches_epv():
    # with growth == terminal == g, DCF > EPV slightly; with growth=0 fading
    # UP to 2.5% terminal it must sit between EPV and a 2.5% perpetuity
    v = lenses.dcf_value(100.0, growth=0.0)
    assert 1000.0 < v < 100 * 1.025 / (0.10 - 0.025) * 1.1


def test_dcf_hand_computed_two_year_case():
    # tiny case we can verify by hand: 2 years, no fade (growth == terminal)
    v = lenses.dcf_value(100.0, growth=0.05, years=2, terminal=0.05, discount=0.10)
    y1, y2 = 105.0, 110.25
    tv = y2 * 1.05 / (0.10 - 0.05)
    expected = y1 / 1.1 + y2 / 1.21 + tv / 1.21
    assert v == pytest.approx(expected)


def test_dcf_growth_monotonicity_and_range():
    lo = lenses.dcf_value(100.0, 0.03)
    mid = lenses.dcf_value(100.0, 0.05)
    hi = lenses.dcf_value(100.0, 0.07)
    assert lo < mid < hi


def test_reverse_dcf_roundtrip():
    fair = lenses.dcf_value(100.0, 0.06)
    implied = lenses.reverse_dcf(fair, 100.0)
    assert implied == pytest.approx(0.06, abs=1e-3)
    assert np.isnan(lenses.reverse_dcf(fair * 100, 100.0))  # absurd price


def test_oe_yield_value_subtracts_net_debt():
    # fair EV = 100 / (0.045 + 0.04) = 1176.5; equity = EV - 200
    v = lenses.oe_yield_value(100.0, net_debt=200.0, t10=0.045)
    assert v == pytest.approx(100 / 0.085 - 200, rel=1e-4)


def _quality_row(ticker="TST", oe=100.0, cagr=0.06, moat=True):
    return {
        "ticker": ticker, "owner_earnings_3y_avg": oe, "rev_cagr_10y": cagr,
        "moat_flag": moat, "roic_median_10y": 0.2, "years_of_data": 11,
    }


def _fund_row(ticker="TST"):
    return {
        "ticker": ticker, "period_type": "FY", "period_end": "2025-12-31",
        "lt_debt": 100.0, "st_debt": 0.0, "cash": 300.0,  # net cash 200
    }


def _dq_row(ticker="TST", eject=False, demote=0):
    return {"ticker": ticker, "eject": eject, "demote_count": demote,
            "demote_reasons": "", "eject_reasons": "", "needs_human_review": "x"}


def test_build_valuations_mos_uses_most_conservative():
    quality = pd.DataFrame([_quality_row()])
    fund = pd.DataFrame([_fund_row()])
    uni = pd.DataFrame([{"ticker": "TST", "cap_b": 800 / 1e9}])  # $800 toy market cap
    disq = pd.DataFrame([_dq_row()])
    out = lenses.build_valuations(quality, fund, uni, disq, t10=0.045).iloc[0]

    assert out["value_conservative"] == pytest.approx(
        min(out["value_oe_yield"], out["value_dcf"], out["value_epv"])
    )
    # EPV = 1000; yield lens = 100/.085 + 200 net cash = 1376; DCF(6%) > EPV
    assert out["value_conservative"] == pytest.approx(1000.0)
    assert out["margin_of_safety"] == pytest.approx(1 - 800 / 1000)
    assert out["verdict"] == "watch (needs price)"  # 20%: above watch bar, below buy bar


def test_verdicts_and_demotions():
    quality = pd.DataFrame([
        _quality_row("BUY", oe=100.0),
        _quality_row("DEMOTED", oe=100.0),
        _quality_row("EJECT", oe=100.0),
        _quality_row("NOMOAT", oe=100.0, moat=False),
    ])
    fund = pd.DataFrame([_fund_row(t) for t in ["BUY", "DEMOTED", "EJECT", "NOMOAT"]])
    uni = pd.DataFrame(
        {"ticker": ["BUY", "DEMOTED", "EJECT", "NOMOAT"], "cap_b": [600 / 1e9] * 4}
    )
    disq = pd.DataFrame([
        _dq_row("BUY"), _dq_row("DEMOTED", demote=1),
        _dq_row("EJECT", eject=True), _dq_row("NOMOAT"),
    ])
    out = lenses.build_valuations(quality, fund, uni, disq, t10=0.045).set_index("ticker")

    assert out.loc["BUY", "verdict"] == "buy candidate"          # 40% MoS
    assert out.loc["DEMOTED", "rank_score"] == pytest.approx(0.20)  # halved
    assert out.loc["DEMOTED", "verdict"] == "watch (needs price)"
    assert out.loc["EJECT", "verdict"] == "ejected" and out.loc["EJECT", "rank_score"] == 0
    assert out.loc["NOMOAT", "verdict"] == "no moat evidence"
    assert list(out.index[:1]) == ["BUY"], "ranked by score"
