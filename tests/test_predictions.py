from datetime import date

import numpy as np
import pandas as pd
import pytest

from log import predictions


def _scored(ticker="RICH", earnings_date=date(2026, 7, 16), **over):
    row = {
        "ticker": ticker, "earnings_date": earnings_date, "session": "BMO",
        "expiry": "2026-07-17", "spot": 100.0, "atm_strike": 100.0,
        "fair_move": 0.06, "ci_low": 0.05, "ci_high": 0.07,
        "implied_move_bid": 0.0975, "implied_move_mid": 0.10, "implied_move_ask": 0.1025,
        "straddle_bid": 9.75, "straddle_mid": 10.0, "straddle_ask": 10.25,
        "edge": 0.66, "z": 5.0, "score": 4.0, "structure": "iron fly",
        "detail": "short 100 straddle @ bid, long 90P / 110C @ ask",
        "entry_side": "credit", "entry_price": 805.0, "max_gain": 805.0, "max_loss": 195.0,
        "spread_pct": 0.05, "open_interest": 1500, "n_events": 10, "conf_mult": 0.8,
        "screened": False, "screen_reason": "", "flags": "",
    }
    row.update(over)
    return pd.DataFrame([row])


def test_registers_future_event_once(tmp_path):
    path = tmp_path / "predictions.csv"
    today = date(2026, 7, 12)

    first = predictions.register(_scored(), today=today, path=path)
    assert len(first) == 1
    again = predictions.register(_scored(entry_price=999.0), today=today, path=path)
    assert len(again) == 0, "same (ticker, date) must never be re-registered"

    saved = pd.read_csv(path)
    assert len(saved) == 1
    assert saved.loc[0, "entry_price"] == 805.0, "frozen row must keep original prices"
    assert saved.loc[0, "entry_side"] == "credit"


def test_past_and_same_day_events_are_not_registered(tmp_path):
    path = tmp_path / "predictions.csv"
    today = date(2026, 7, 16)
    out = predictions.register(
        pd.concat([
            _scored(ticker="TODAY", earnings_date=date(2026, 7, 16)),
            _scored(ticker="PAST", earnings_date=date(2026, 7, 10)),
            _scored(ticker="FUT", earnings_date=date(2026, 7, 17)),
        ]),
        today=today, path=path,
    )
    assert list(out["ticker"]) == ["FUT"]


def test_appends_without_rewriting_prior_rows(tmp_path):
    path = tmp_path / "predictions.csv"
    predictions.register(_scored(ticker="AAA"), today=date(2026, 7, 12), path=path)
    original_first_line = path.read_text().splitlines()[1]

    predictions.register(_scored(ticker="BBB"), today=date(2026, 7, 12), path=path)
    lines = path.read_text().splitlines()
    assert lines[1] == original_first_line, "existing rows must be byte-identical"
    assert len(lines) == 3  # header + 2 rows

    saved = pd.read_csv(path)
    assert list(saved["ticker"]) == ["AAA", "BBB"]


def test_screened_and_inf_rows_round_trip(tmp_path):
    path = tmp_path / "predictions.csv"
    scored = _scored(
        ticker="LONGVOL", structure="long straddle", entry_side="debit",
        entry_price=240.0, max_gain=np.inf, max_loss=240.0,
    )
    scored = pd.concat([
        scored,
        _scored(ticker="WIDE", screened=True, screen_reason="spread > 10%",
                structure="screened out", entry_price=np.nan,
                max_gain=np.nan, max_loss=np.nan),
    ])
    out = predictions.register(scored, today=date(2026, 7, 12), path=path)
    assert len(out) == 2, "screened events are registered too (calibration needs them)"
    saved = pd.read_csv(path)
    assert saved.loc[0, "max_gain"] == np.inf
    assert pd.isna(saved.loc[1, "entry_price"])


def test_corrupt_log_refuses_append(tmp_path):
    path = tmp_path / "predictions.csv"
    path.write_text("not,a,predictions,log\n1,2,3,4\n")
    with pytest.raises(RuntimeError):
        predictions.register(_scored(), today=date(2026, 7, 12), path=path)
