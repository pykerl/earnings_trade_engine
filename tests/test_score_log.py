from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import score_log


def test_iron_fly_pnl_at_expiry():
    row = pd.Series({
        "structure": "iron fly", "entry_price": 805.0,
        "detail": "short 100 straddle @ bid, long 90P / 110C @ ask",
    })
    assert score_log.structure_pnl(row, settle=100.0) == pytest.approx(805.0)   # pinned
    assert score_log.structure_pnl(row, settle=105.0) == pytest.approx(305.0)   # 5 in
    assert score_log.structure_pnl(row, settle=120.0) == pytest.approx(-195.0)  # capped
    assert score_log.structure_pnl(row, settle=80.0) == pytest.approx(-195.0)   # capped down


def test_straddle_and_strangle_pnl():
    st = pd.Series({"structure": "long straddle", "entry_price": 240.0,
                    "detail": "long 50 straddle @ ask"})
    assert score_log.structure_pnl(st, settle=55.0) == pytest.approx(260.0)
    assert score_log.structure_pnl(st, settle=50.0) == pytest.approx(-240.0)
    sg = pd.Series({"structure": "long strangle", "entry_price": 170.0,
                    "detail": "long 90P / 110C @ ask"})
    assert score_log.structure_pnl(sg, settle=115.0) == pytest.approx(330.0)
    assert score_log.structure_pnl(sg, settle=100.0) == pytest.approx(-170.0)


def test_unparseable_or_no_trade_returns_none():
    assert score_log.structure_pnl(
        pd.Series({"structure": "no trade", "entry_price": np.nan, "detail": ""}), 100.0
    ) is None


def test_score_alignment_and_calibration():
    days = pd.bdate_range("2026-07-09", "2026-07-17")
    closes = {"2026-07-13": 100.0, "2026-07-14": 103.0, "2026-07-17": 102.0}
    px_rows = []
    base = 100.0
    for d in days:
        key = d.strftime("%Y-%m-%d")
        px_rows.append({"ticker": "JPM", "date": d, "adj_close": closes.get(key, base)})
    prices = pd.DataFrame(px_rows)
    preds = pd.DataFrame([{
        "ticker": "JPM", "earnings_date": "2026-07-14", "session": "BMO",
        "structure": "iron fly", "detail": "short 100 straddle @ bid, long 95P / 105C @ ask",
        "entry_price": 400.0, "expiry": "2026-07-17",
        "implied_move_mid": 0.035, "fair_move": 0.026, "screened": False,
        "atm_strike": 100.0, "straddle_bid": 3.4, "straddle_ask": 3.6, "spot": 100.0,
    }])
    scored = score_log.score(preds, prices, today=date(2026, 7, 20))
    assert len(scored) == 1
    r = scored.iloc[0]
    # BMO: close(7/13)=100 -> close(7/14)=103 = +3%
    assert r["realized_move"] == pytest.approx(0.03)
    assert r["inside_implied"]  # 3% < 3.5%
    # settle 102: intrinsic 2 -> pnl = 400 - 200
    assert r["pnl"] == pytest.approx(200.0)
    # hypothetical straddles at frozen quotes, settle 102 (intrinsic $200):
    assert r["short_straddle_pnl"] == pytest.approx(340.0 - 200.0)
    assert r["long_straddle_pnl"] == pytest.approx(200.0 - 360.0)
    # edge (3.5 vs 2.6 fair) = +34.6% -> rich bucket, aligned = short side
    assert r["edge_bucket"].startswith("rich")
    assert r["model_aligned_pnl"] == pytest.approx(140.0)


def test_unresolved_events_are_skipped():
    preds = pd.DataFrame([{
        "ticker": "JPM", "earnings_date": "2026-07-28", "session": "BMO",
        "structure": "no trade", "detail": "", "entry_price": np.nan,
        "expiry": "2026-07-31", "implied_move_mid": 0.03, "fair_move": 0.03,
        "screened": False, "atm_strike": np.nan, "straddle_bid": np.nan,
        "straddle_ask": np.nan, "spot": np.nan,
    }])
    prices = pd.DataFrame({"ticker": ["JPM"], "date": [pd.Timestamp("2026-07-13")],
                           "adj_close": [100.0]})
    assert score_log.score(preds, prices, today=date(2026, 7, 20)).empty
