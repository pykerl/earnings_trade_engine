from datetime import date

import numpy as np
import pandas as pd
import pytest

from common import config
from scoring import rank


def _ladder(ticker="RICH", expiry="2026-07-17"):
    return pd.DataFrame(
        {
            "ticker": ticker,
            "expiry": expiry,
            "strike": [80.0, 90.0, 95.0, 100.0, 105.0, 110.0, 120.0],
            "call_bid": [19.0, 10.5, 6.2, 4.9, 2.8, 1.1, 0.2],
            "call_ask": [21.0, 11.0, 6.6, 5.1, 3.0, 1.3, 0.3],
            "put_bid": [0.1, 0.3, 1.0, 4.85, 6.0, 10.2, 19.0],
            "put_ask": [0.2, 0.4, 1.2, 5.15, 6.4, 10.8, 21.0],
            "call_oi": [10, 100, 300, 800, 400, 150, 20],
            "put_oi": [20, 200, 350, 700, 250, 90, 10],
        }
    )


def _row(**over):
    base = {
        "ticker": "RICH", "earnings_date": date(2026, 7, 16), "session": "BMO",
        "spot": 100.0, "expiry": "2026-07-17", "atm_strike": 100.0,
        "straddle_bid": 9.75, "straddle_mid": 10.0, "straddle_ask": 10.25,
        "implied_move_bid": 0.0975, "implied_move_mid": 0.10, "implied_move_ask": 0.1025,
        "spread_pct": 0.05, "open_interest": 1500, "volume": 5000, "quote_ok": True,
        "edge": 0.6, "z": 4.0, "screened": False,
    }
    base.update(over)
    return pd.Series(base)


def test_liquidity_multiplier_shape():
    assert rank.liquidity_multiplier(0.05) == 1.0
    assert rank.liquidity_multiplier(config.SOFT_SPREAD_PCT) == 1.0
    assert rank.liquidity_multiplier(0.09) == pytest.approx(0.5)
    assert rank.liquidity_multiplier(config.MAX_SPREAD_PCT) == 0.0
    assert rank.liquidity_multiplier(0.5) == 0.0


def test_iron_fly_respects_max_loss_and_prices_at_bid_ask():
    fly = rank.map_iron_fly(_row(), _ladder())
    # 105/95 wings: credit = 9.75 - 3.0 - 1.2 = 5.55, width 5 -> max loss $-55? no:
    # (5 - 5.55) < 0 -> invalid; next 110/90: credit = 9.75 - 1.3 - 0.4 = 8.05,
    # width 10 -> max loss (10 - 8.05)*100 = $195 <= $250
    assert fly is not None
    assert fly["structure"] == "iron fly"
    assert fly["max_loss"] == pytest.approx(195.0)
    assert fly["max_gain"] == pytest.approx(805.0)
    assert "110" in fly["detail"] and "90" in fly["detail"]


def test_iron_fly_none_when_nothing_fits_budget():
    ladder = _ladder()
    ladder[["call_ask", "put_ask"]] = 0.01  # wings cost nothing -> credit ~ straddle bid
    row = _row(straddle_bid=1.0)  # tiny credit, width >= 5 -> max loss >= $380
    assert rank.map_iron_fly(row, ladder) is None


def test_long_straddle_when_debit_fits():
    row = _row(straddle_ask=2.4, edge=-0.5, z=-3.0)
    got = rank.map_long_vol(row, _ladder())
    assert got["structure"] == "long straddle"
    assert got["entry_price"] == pytest.approx(240.0)
    assert got["max_loss"] == pytest.approx(240.0)
    assert np.isinf(got["max_gain"])


def test_strangle_fallback_when_straddle_too_dear():
    got = rank.map_long_vol(_row(edge=-0.5, z=-3.0), _ladder())  # straddle ask $1025
    # nearest affordable pair: 110C @ 1.3 + 90P @ 0.4 -> $170
    assert got["structure"] == "long strangle"
    assert got["entry_price"] == pytest.approx(170.0)


def test_map_structure_no_trade_inside_band():
    assert rank.map_structure(_row(edge=0.05, z=4.0), _ladder())["structure"] == "no trade"
    assert rank.map_structure(_row(edge=0.5, z=0.5), _ladder())["structure"] == "no trade"


def _scoring_inputs():
    chains = pd.DataFrame([
        dict(_row()),
        dict(_row(ticker="WIDE", spread_pct=0.12, straddle_bid=8.8, straddle_ask=11.2)),
        dict(_row(ticker="THIN", open_interest=120)),
    ]).drop(columns=["edge", "z", "screened"])
    fair = pd.DataFrame(
        {
            "ticker": ["RICH", "WIDE", "THIN"],
            "fair_move": [0.06, 0.06, 0.06],
            "ci_low": [0.05, 0.05, 0.05],
            "ci_high": [0.07, 0.07, 0.07],
            "n_events": [10, 10, 10],
            "w_name": [0.625, 0.625, 0.625],
            "name_mean": [0.06] * 3, "pool": ["g"] * 3, "pool_mean": [0.05] * 3,
            "t_nu": [5.0] * 3, "t_scale": [0.03] * 3,
            "low_conf_share": [0.0, 0.0, 0.0],
        }
    )
    events = pd.DataFrame(
        {
            "ticker": ["RICH", "WIDE", "THIN"],
            "source_agreement": ["confirmed"] * 3,
            "name": ["Rich Co", "Wide Co", "Thin Co"],
            "sector": ["Financials"] * 3,
        }
    )
    ladders = pd.concat([_ladder("RICH"), _ladder("WIDE"), _ladder("THIN")], ignore_index=True)
    return chains, fair, events, ladders


def test_score_events_screens_scores_and_ranks():
    scored = rank.score_events(*_scoring_inputs()).set_index("ticker")

    # edge = (0.10 - 0.06) / 0.06
    assert scored.loc["RICH", "edge"] == pytest.approx(0.6667, abs=1e-3)
    assert not scored.loc["RICH", "screened"]
    assert scored.loc["RICH", "structure"] == "iron fly"
    assert scored.loc["RICH", "entry_side"] == "credit"
    assert scored.loc["RICH", "max_loss"] <= config.MAX_LOSS_DOLLARS

    assert scored.loc["WIDE", "screened"]
    assert scored.loc["WIDE", "structure"] == "screened out"
    assert scored.loc["WIDE", "score"] == 0.0
    assert "spread" in scored.loc["WIDE", "screen_reason"]

    assert scored.loc["THIN", "screened"]
    assert "OI" in scored.loc["THIN", "screen_reason"]

    # unscreened first, then screened
    assert list(scored.index[:1]) == ["RICH"]
    assert scored.loc["RICH", "spread_cost_pct_of_edge"] == pytest.approx(
        100 * (10.25 - 9.75) / ((0.10 - 0.06) * 100), abs=1e-6
    )
