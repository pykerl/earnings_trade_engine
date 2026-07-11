from datetime import date

import pandas as pd
import pytest

from ingest import chains


def test_reaction_day_bmo_is_event_day():
    assert chains.reaction_day(date(2026, 7, 14), "BMO") == date(2026, 7, 14)


def test_reaction_day_amc_is_next_trading_day():
    assert chains.reaction_day(date(2026, 7, 14), "AMC") == date(2026, 7, 15)
    # AMC on a Friday -> Monday
    assert chains.reaction_day(date(2026, 7, 17), "AMC") == date(2026, 7, 20)
    # unknown treated like AMC (safe side: expiry must outlive the move)
    assert chains.reaction_day(date(2026, 7, 14), "unknown") == date(2026, 7, 15)


def test_pick_expiry_first_on_or_after_reaction():
    exps = ["2026-07-10", "2026-07-17", "2026-07-24"]
    assert chains.pick_expiry(exps, date(2026, 7, 15)) == "2026-07-17"
    assert chains.pick_expiry(exps, date(2026, 7, 17)) == "2026-07-17"
    assert chains.pick_expiry(exps, date(2026, 7, 25)) is None


def _chain_frames():
    calls = pd.DataFrame(
        {
            "strike": [90.0, 95.0, 100.0, 105.0, 110.0, 200.0],
            "bid": [10.5, 6.2, 3.0, 1.1, 0.4, 0.0],
            "ask": [11.0, 6.6, 3.2, 1.3, 0.5, 0.1],
            "openInterest": [100, 300, 800, 400, 150, 0],
            "volume": [10, 20, 50, 30, 5, 0],
        }
    )
    puts = pd.DataFrame(
        {
            "strike": [90.0, 95.0, 100.0, 105.0, 110.0],
            "bid": [0.3, 1.0, 2.9, 6.0, 10.2],
            "ask": [0.4, 1.2, 3.1, 6.4, 10.8],
            "openInterest": [200, 350, 700, 250, 90],
            "volume": [5, 15, 40, 20, 3],
        }
    )
    return calls, puts


def test_ladder_window_and_summary_atm_straddle():
    calls, puts = _chain_frames()
    ladder = chains.build_ladder(calls, puts, spot=100.0)
    assert 200.0 not in set(ladder["strike"]), "strikes outside ±20% excluded"

    s = chains.summarize_event(ladder, spot=100.0)
    assert s["atm_strike"] == 100.0
    assert s["straddle_bid"] == pytest.approx(3.0 + 2.9)
    assert s["straddle_ask"] == pytest.approx(3.2 + 3.1)
    assert s["straddle_mid"] == pytest.approx((5.9 + 6.3) / 2)
    assert s["implied_move_mid"] == pytest.approx(6.1 / 100.0)
    assert s["spread_pct"] == pytest.approx(0.4 / 6.1)
    assert s["open_interest"] == 1500
    assert s["quote_ok"]


def test_summary_flags_dead_quotes():
    calls, puts = _chain_frames()
    calls.loc[calls["strike"] == 100.0, "bid"] = 0.0
    puts.loc[puts["strike"] == 100.0, "bid"] = 0.0
    ladder = chains.build_ladder(calls, puts, spot=100.0)
    s = chains.summarize_event(ladder, spot=100.0)
    assert not s["quote_ok"]


def test_summary_none_when_no_two_sided_quotes():
    calls, puts = _chain_frames()
    calls["ask"] = 0.0
    ladder = chains.build_ladder(calls, puts, spot=100.0)
    assert chains.summarize_event(ladder, spot=100.0) is None
