from datetime import date

import numpy as np
import pandas as pd
import pytest

from features import moves


@pytest.fixture
def px():
    # Mon Jul 6 .. Fri Jul 17 2026, ten trading days
    days = pd.bdate_range("2026-07-06", "2026-07-17")
    closes = [100.0, 101.0, 102.0, 100.0, 108.0, 109.0, 110.0, 121.0, 122.0, 123.0]
    return pd.DataFrame(
        {
            "ticker": "TST",
            "date": days,
            "open": closes, "high": closes, "low": closes, "close": closes,
            "adj_close": closes,
            "volume": 1_000_000,
        }
    )


def _hist(event_date, session):
    return pd.DataFrame(
        [{"ticker": "TST", "event_date": event_date, "session": session,
          "eps_estimate": np.nan, "reported_eps": np.nan, "surprise_pct": np.nan,
          "source": "yfinance"}]
    )


def test_bmo_move_is_same_day_close_over_prior_close(px):
    # BMO on Thu Jul 9: close(Jul 9)=100 vs close(Jul 8)=102 -> -1.96%
    out = moves.compute_moves(_hist(date(2026, 7, 9), "BMO"), px)
    assert len(out) == 1
    assert out.loc[0, "move"] == pytest.approx(100.0 / 102.0 - 1)
    assert out.loc[0, "confidence"] == "high"


def test_amc_move_is_next_day_close_over_event_close(px):
    # AMC on Thu Jul 9: close(Jul 10)=108 vs close(Jul 9)=100 -> +8%
    out = moves.compute_moves(_hist(date(2026, 7, 9), "AMC"), px)
    assert out.loc[0, "move"] == pytest.approx(0.08)
    assert out.loc[0, "confidence"] == "high"


def test_unknown_takes_larger_of_day_and_next_day(px):
    # Jul 9 unknown: same-day -1.96% vs next-day +8% -> +8%, low confidence
    out = moves.compute_moves(_hist(date(2026, 7, 9), "unknown"), px)
    assert out.loc[0, "move"] == pytest.approx(0.08)
    assert out.loc[0, "abs_move"] == pytest.approx(0.08)
    assert out.loc[0, "confidence"] == "low"


def test_weekend_event_date_rolls_to_next_trading_day(px):
    # Sat Jul 11, BMO: reaction is Mon Jul 13 close(109) over Fri Jul 10 (108)
    out = moves.compute_moves(_hist(date(2026, 7, 11), "BMO"), px)
    assert out.loc[0, "move"] == pytest.approx(109.0 / 108.0 - 1)


def test_amc_on_last_covered_day_is_skipped(px):
    # AMC on the final price date has no next-day close -> event skipped
    out = moves.compute_moves(_hist(date(2026, 7, 17), "AMC"), px)
    assert out.empty


def test_event_before_coverage_is_skipped(px):
    out = moves.compute_moves(_hist(date(2026, 7, 6), "BMO"), px)  # no prior close
    assert out.empty


def test_ticker_without_prices_is_skipped(px):
    hist = _hist(date(2026, 7, 9), "BMO")
    hist.loc[0, "ticker"] = "NOPX"
    out = moves.compute_moves(hist, px)
    assert out.empty
