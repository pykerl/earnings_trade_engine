from datetime import date

import numpy as np
import pandas as pd

from common import config
from scoring import squeeze


def _positioning():
    return pd.DataFrame(
        {
            "ticker": ["HOT", "WARM", "COLD"],
            "float_shares": [50e6, 500e6, 5e9],
            "shares_outstanding": [60e6, 550e6, 5.5e9],
            "inst_pct": [0.35, 0.60, 0.80],
            "insider_pct": [0.10, 0.05, 0.01],
            "retail_pct": [0.55, 0.35, 0.19],
            "si_shares": [12e6, 25e6, 30e6],
            "si_pct_float": [0.24, 0.05, 0.006],
            "days_to_cover": [6.0, 2.0, 1.0],
            "avg_vol_10d": [8e6, 10e6, 30e6],
            "float_turnover": [0.16, 0.02, 0.006],
            "si_trend": [0.20, -0.05, 0.0],
            "si_source": ["nasdaq", "yahoo", "yahoo"],
        }
    )


def _events():
    return pd.DataFrame(
        {
            "ticker": ["HOT", "WARM", "COLD"],
            "earnings_date": [date(2026, 7, 16)] * 3,
            "session": ["AMC"] * 3,
            "name": ["Hot Co", "Warm Co", "Cold Co"],
            "sector": ["Tech"] * 3,
        }
    )


def _chains():
    return pd.DataFrame(
        [{"ticker": "HOT", "spot": 20.0, "expiry": "2026-07-17", "implied_move_mid": 0.15}]
    )


def _ladder():
    return pd.DataFrame(
        {
            "ticker": "HOT", "expiry": "2026-07-17",
            "strike": [20.0, 22.0, 23.0, 25.0],
            "call_bid": [1.5, 0.9, 0.6, 0.2],
            "call_ask": [1.7, 1.1, 0.8, 0.3],
            "put_bid": [1.4, 2.6, 3.4, 5.1],
            "put_ask": [1.6, 2.9, 3.7, 5.5],
            "call_oi": [500] * 4, "put_oi": [400] * 4,
        }
    )


def test_scores_rank_the_crowded_short_highest():
    scores = squeeze.squeeze_scores(_positioning())
    assert scores.iloc[0] > scores.iloc[1] > scores.iloc[2]
    assert 0 <= scores.min() and scores.max() <= 100


def test_watch_flags_candidates_and_risk():
    watch = squeeze.build_squeeze_watch(
        _events(), _positioning(), _chains(), _ladder(), today=date(2026, 7, 11)
    ).set_index("ticker")
    assert bool(watch.loc["HOT", "candidate"])
    assert bool(watch.loc["HOT", "squeeze_risk"])       # 24% >= 8%
    assert not bool(watch.loc["WARM", "squeeze_risk"])  # 5% < 8%
    assert not bool(watch.loc["COLD", "candidate"])


def test_candidate_gets_affordable_call_at_implied_move():
    watch = squeeze.build_squeeze_watch(
        _events(), _positioning(), _chains(), _ladder(), today=date(2026, 7, 11)
    ).set_index("ticker")
    hot = watch.loc["HOT"]
    # one implied move up = 20 * 1.15 = 23 -> the 23C at ask 0.8 = $80 <= $250
    assert hot["structure"] == "long call"
    assert hot["strike"] == 23.0
    assert hot["entry_price"] == 80.0
    assert hot["max_loss"] == 80.0
    assert np.isinf(hot["max_gain"])
    # names without chains stay watch-only
    assert watch.loc["WARM", "structure"] == "watch only"


def test_no_affordable_call_is_reported():
    ladder = _ladder()
    ladder["call_ask"] = 9.9  # every call costs $990
    watch = squeeze.build_squeeze_watch(
        _events(), _positioning(), _chains(), ladder, today=date(2026, 7, 11)
    ).set_index("ticker")
    assert watch.loc["HOT", "structure"] == "no affordable call"


def test_plan_excludes_credit_structures_on_squeeze_risk():
    from scoring.size import build_trade_plan
    from tests.test_size import _row

    scored = pd.DataFrame([
        dict(_row("SAFE", score=2.0), squeeze_risk=False),
        dict(_row("SQZD", score=9.0), squeeze_risk=True),   # crowded short iron fly
    ])
    plan = build_trade_plan(scored, today=date(2026, 7, 11))
    assert list(plan["ticker"]) == ["SAFE"], "no short premium on squeeze candidates"
