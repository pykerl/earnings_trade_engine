from datetime import date

import numpy as np
import pandas as pd
import pytest

from autopsy import cohorts as au


@pytest.fixture
def px():
    idx = pd.bdate_range("2026-01-02", periods=120)
    return pd.DataFrame(
        {
            "WIN": np.linspace(100, 200, len(idx)),     # +100%
            "FLAT": np.full(len(idx), 50.0),            # 0%
            "LOSE": np.linspace(40, 30, len(idx)),      # -25%
            "SPY": np.linspace(100, 110, len(idx)),     # +10%
        },
        index=idx,
    )


def test_ew_curve_and_total_return(px):
    curve = au.ew_curve(px, ["WIN", "FLAT", "LOSE"], date(2026, 1, 2))
    # EW of +100%, 0%, -25% = +25%
    assert au.total_return(curve) == pytest.approx(0.25, abs=1e-9)
    assert curve.iloc[0] == pytest.approx(1.0)


def test_missing_tickers_are_skipped_not_fatal(px):
    curve = au.ew_curve(px, ["WIN", "GHOST"], date(2026, 1, 2))
    assert au.total_return(curve) == pytest.approx(1.0)  # WIN alone
    assert au.ew_curve(px, ["GHOST"], date(2026, 1, 2)) is None


def test_max_drawdown():
    curve = pd.Series([1.0, 1.5, 0.9, 1.2])
    assert au.max_drawdown(curve) == pytest.approx(0.9 / 1.5 - 1)


def test_contribution_concentration(px):
    names = au.per_name_returns(px, ["WIN", "FLAT", "LOSE"], date(2026, 1, 2))
    conc = au.contribution_concentration(names)
    assert conc["portfolio_return"] == pytest.approx(0.25)
    assert conc["top2_names"][0] == "WIN"
    assert conc["hit_rate"] == pytest.approx(1 / 3)
    # WIN contributes 33.3pts of the 25% -> share > 1 (losers dragged)
    assert conc["top2_share"] > 1.0


def test_entry_lag_uses_later_base(px):
    full = au.total_return(au.ew_curve(px, ["WIN"], date(2026, 1, 2)))
    lagged = au.total_return(au.ew_curve(px, ["WIN"], date(2026, 3, 2)))
    assert lagged < full


FF_CSV = """This file was created by CMPT_ME_BEME_RETS using the 202605 CRSP database.
The 1-month TBill return is from Ibbotson and Associates Inc.

,Mkt-RF,SMB,HML,RF
19260701,    0.10,   -0.24,   -0.28,   0.009
20260108,    1.50,    0.20,   -0.10,   0.017
20260109,   -0.75,    0.05,    0.02,   0.017
"""


def test_parse_ff_csv():
    ff = au.parse_ff_csv(FF_CSV)
    assert list(ff.columns) == ["Mkt-RF", "SMB", "HML", "RF"]
    assert ff.iloc[1]["Mkt-RF"] == pytest.approx(0.015)
    assert ff.index[1] == pd.Timestamp("2026-01-08")


MOM_CSV = """This file was created by using the 202605 CRSP database.  It,,
contains a momentum factor, with trailing commas everywhere,,
,Mom,,
19270103,    0.56,
20260528,     .12,
20260529,-1.68,
,,
Copyright 2026 Eugene F. Fama and Kenneth R. French,,
"""


def test_parse_ff_momentum_trailing_commas():
    mom = au.parse_ff_csv(MOM_CSV)
    assert list(mom.columns) == ["Mom"]
    assert len(mom) == 3
    assert mom.iloc[-1]["Mom"] == pytest.approx(-0.0168)


def test_factor_decomposition_recovers_beta():
    rng = np.random.default_rng(3)
    n = 250
    idx = pd.bdate_range("2025-01-02", periods=n)
    mkt = rng.normal(0.0005, 0.01, n)
    mom = rng.normal(0.0, 0.006, n)
    rf = np.full(n, 0.00015)
    port_ret = rf + 1.5 * mkt + 0.5 * mom + 0.0002  # daily alpha 2bp
    curve = pd.Series(np.cumprod(1 + port_ret + rf * 0), index=idx)
    ff = pd.DataFrame({"MKT_RF": mkt, "SMB": 0.0, "HML": 0.0, "RF": rf, "MOM": mom}, index=idx)
    f = au.factor_decomposition(curve, ff)
    assert f["beta_market"] == pytest.approx(1.5, abs=0.1)
    assert f["beta_momentum"] == pytest.approx(0.5, abs=0.15)
    assert f["alpha_annualized"] == pytest.approx((1.0002) ** 252 - 1, rel=0.5)
    assert f["r2"] > 0.8


def test_cohorts_yaml_loads_with_verification_flags():
    cfg = au.load_cohorts()
    c = cfg["cohorts"]
    assert c["wsb_2026_index"]["constituents_verified"] is True
    assert len(c["wsb_2026_index"]["tickers"]) == 10
    assert c["wsb_2025"]["constituents_verified"] is False
    assert "verification_note" in c["wsb_2025"]
    assert set(c["wsb_2026_upvotes"]["tickers"]) >= {"POET", "SOFI", "PATH"}
    for cohort in c.values():
        assert cohort["sources"], "every cohort needs cited sources"
