import json
from datetime import date

import numpy as np
import pandas as pd
import pytest

from scoring import size
from scoring.rank import entry_deadline, next_trading_session

FLY_LEGS = json.dumps([
    {"action": "SELL", "right": "CALL", "strike": 100.0},
    {"action": "SELL", "right": "PUT", "strike": 100.0},
    {"action": "BUY", "right": "CALL", "strike": 110.0},
    {"action": "BUY", "right": "PUT", "strike": 90.0},
])


def _row(ticker, score, max_loss=200.0, name=None, **over):
    row = {
        "ticker": ticker, "name": name or f"{ticker} Co", "sector": "Tech",
        "earnings_date": date(2026, 7, 16), "session": "AMC",
        "entry_by": date(2026, 7, 16), "expiry": "2026-07-17", "spot": 100.0,
        "structure": "iron fly", "entry_side": "credit", "entry_price": 500.0,
        "max_gain": 500.0, "max_loss": max_loss, "screened": False,
        "score": score, "edge": 0.4, "implied_move_mid": 0.08, "fair_move": 0.055,
        "n_events": 10, "legs_json": FLY_LEGS,
    }
    row.update(over)
    return row


def test_entry_deadline_rules():
    # BMO Tue -> Mon; AMC Thu -> Thu; unknown treated like BMO; weekend rolls back
    assert entry_deadline(date(2026, 7, 14), "BMO") == date(2026, 7, 13)
    assert entry_deadline(date(2026, 7, 16), "AMC") == date(2026, 7, 16)
    assert entry_deadline(date(2026, 7, 14), "unknown") == date(2026, 7, 13)
    assert entry_deadline(date(2026, 7, 13), "BMO") == date(2026, 7, 10)  # Mon -> prior Fri
    assert next_trading_session(date(2026, 7, 11)) == date(2026, 7, 13)  # Sat -> Mon


def test_plan_orders_by_score_and_respects_budget():
    scored = pd.DataFrame([
        _row("AAA", score=5.0, max_loss=240.0),
        _row("BBB", score=4.0, max_loss=240.0),
        _row("CCC", score=3.0, max_loss=240.0),
        _row("DDD", score=2.0, max_loss=240.0),
        _row("EEE", score=1.0, max_loss=240.0),
        _row("FFF", score=6.0, max_loss=240.0, screened=True),  # screened: excluded
        _row("GGG", score=6.0, structure="no trade"),           # not actionable
    ])
    plan = size.build_trade_plan(scored, today=date(2026, 7, 11), account=10_000)
    # per-name cap $500 -> 2 contracts x $240 = $480 each; budget $2500
    # AAA 480, BBB 480, CCC 480, DDD 480 (=1920), EEE fits 480 -> 2400
    assert list(plan["ticker"]) == ["AAA", "BBB", "CCC", "DDD", "EEE"]
    assert (plan["contracts"] == 2).all()
    assert plan["position_risk"].sum() <= 2500
    assert "FFF" not in set(plan["ticker"]) and "GGG" not in set(plan["ticker"])


def test_plan_dedupes_share_classes():
    scored = pd.DataFrame([
        _row("GOOGL", score=4.0, name="Alphabet Inc. (Class A)"),
        _row("GOOG", score=3.5, name="Alphabet Inc. (Class C)"),
    ])
    plan = size.build_trade_plan(scored, today=date(2026, 7, 11))
    assert list(plan["ticker"]) == ["GOOGL"], "same company must appear once, best class wins"


def test_plan_skips_events_whose_entry_window_passed():
    scored = pd.DataFrame([
        # BMO Monday Jul 13: entry deadline was Fri Jul 10 -> gone by Sat Jul 11
        _row("LATE", score=9.0, session="BMO", earnings_date=date(2026, 7, 13),
             entry_by=date(2026, 7, 10)),
        _row("OK", score=1.0),
    ])
    plan = size.build_trade_plan(scored, today=date(2026, 7, 11))
    assert list(plan["ticker"]) == ["OK"]


def test_plan_partial_fill_at_budget_edge():
    scored = pd.DataFrame([
        _row("AAA", score=5.0, max_loss=240.0),
        _row("BBB", score=4.0, max_loss=240.0),
        _row("CCC", score=3.0, max_loss=240.0),
    ])
    plan = size.build_trade_plan(scored, today=date(2026, 7, 11), account=10_000,
                                 risk_budget_pct=0.12)  # $1200 budget
    # AAA 2x480, BBB 2x480 -> 960; CCC fits only 1 contract (240 -> 1200)
    got = dict(zip(plan["ticker"], plan["contracts"]))
    assert got == {"AAA": 2, "BBB": 2, "CCC": 1}


def test_debit_cash_flow_sign():
    scored = pd.DataFrame([
        _row("VOL", score=2.0, structure="long straddle", entry_side="debit",
             entry_price=240.0, max_loss=240.0, max_gain=np.inf,
             legs_json=json.dumps([
                 {"action": "BUY", "right": "CALL", "strike": 100.0},
                 {"action": "BUY", "right": "PUT", "strike": 100.0},
             ])),
    ])
    plan = size.build_trade_plan(scored, today=date(2026, 7, 11))
    assert plan.loc[0, "cash_flow"] == pytest.approx(-480.0)  # 2 contracts paid
    assert np.isinf(plan.loc[0, "position_max_gain"])
