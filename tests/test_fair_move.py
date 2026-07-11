from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from common import config
from model import fair_move as fm


def _moves_for(ticker, abs_moves, start=date(2023, 1, 15)):
    rows = []
    for i, m in enumerate(abs_moves):
        sign = 1 if i % 2 == 0 else -1
        rows.append(
            {
                "ticker": ticker,
                "event_date": start + timedelta(days=91 * i),
                "session": "AMC",
                "move": sign * m,
                "abs_move": m,
                "confidence": "high",
            }
        )
    return rows


def _events(tickers, sector="Financials", cap_b=100.0):
    return pd.DataFrame(
        {
            "ticker": tickers,
            "earnings_date": date(2026, 7, 14),
            "session": "BMO",
            "source_agreement": "confirmed",
            "sources": "yfinance,nasdaq",
            "name": tickers,
            "sector": sector,
            "cap_b": cap_b,
        }
    )


def test_cap_bucket_edges():
    assert fm.cap_bucket(5) == "small"
    assert fm.cap_bucket(25) == "mid"
    assert fm.cap_bucket(100) == "large"
    assert fm.cap_bucket(500) == "mega"
    assert fm.cap_bucket(float("nan")) == "unknown"


def test_shrinkage_blend_matches_formula():
    # target name: 6 events all exactly 5%; pool peers all exactly 2%
    moves = pd.DataFrame(
        _moves_for("TGT", [0.05] * 6)
        + _moves_for("P1", [0.02] * 8)
        + _moves_for("P2", [0.02] * 8)
        + _moves_for("P3", [0.02] * 8)
    )
    events = _events(["TGT", "P1", "P2", "P3"])
    fair = fm.estimate_fair_moves(moves, events).set_index("ticker")

    w = 6 / (6 + config.SHRINKAGE_K)  # = 0.5
    # pool = mean of name-level means in sector|bucket = (0.05 + 3*0.02)/4
    pool = (0.05 + 3 * 0.02) / 4
    expected = w * 0.05 + (1 - w) * pool
    row = fair.loc["TGT"]
    assert row["w_name"] == pytest.approx(w)
    assert row["name_mean"] == pytest.approx(0.05)
    assert row["pool_mean"] == pytest.approx(pool)
    assert row["fair_move"] == pytest.approx(expected)
    assert row["pool"] == "Financials|large"
    assert row["ci_low"] <= row["fair_move"] <= row["ci_high"]


def test_no_history_name_gets_pool_estimate():
    moves = pd.DataFrame(
        _moves_for("P1", [0.03] * 8) + _moves_for("P2", [0.03] * 8) + _moves_for("P3", [0.03] * 8)
    )
    events = _events(["NEWBIE", "P1", "P2", "P3"])
    fair = fm.estimate_fair_moves(moves, events).set_index("ticker")
    row = fair.loc["NEWBIE"]
    assert row["n_events"] == 0 and row["w_name"] == 0
    assert row["fair_move"] == pytest.approx(0.03)
    assert row["low_conf_share"] == 1.0


def test_pool_falls_back_to_sector_then_global():
    # only 2 names in the sector x bucket pool -> sector pool also has 2 -> global
    moves = pd.DataFrame(
        _moves_for("A", [0.04] * 8)
        + _moves_for("B", [0.04] * 8)
        + _moves_for("C", [0.02] * 8)
        + _moves_for("D", [0.02] * 8)
    )
    events = pd.concat(
        [_events(["A", "B"], sector="Energy"), _events(["C", "D"], sector="Utilities")],
        ignore_index=True,
    )
    fair = fm.estimate_fair_moves(moves, events).set_index("ticker")
    assert fair.loc["A", "pool"] == "global"
    assert fair.loc["A", "pool_mean"] == pytest.approx(0.03)


def test_recency_weighting_tilts_to_recent_quarters():
    old_heavy = _moves_for("X", [0.10] * 6 + [0.02] * 6)  # recent quarters small
    new_heavy = _moves_for("Y", [0.02] * 6 + [0.10] * 6)  # recent quarters big
    peers = _moves_for("P1", [0.05] * 8) + _moves_for("P2", [0.05] * 8) + _moves_for("P3", [0.05] * 8)
    moves = pd.DataFrame(old_heavy + new_heavy + peers)
    fair = fm.estimate_fair_moves(moves, _events(["X", "Y", "P1", "P2", "P3"])).set_index("ticker")
    assert fair.loc["Y", "name_mean"] > fair.loc["X", "name_mean"]


def test_t_fit_is_finite_and_sane():
    rng = np.random.default_rng(7)
    abs_moves = np.abs(rng.standard_t(df=4, size=12) * 0.03)
    moves = pd.DataFrame(
        _moves_for("T1", list(abs_moves)) + _moves_for("P1", [0.03] * 8)
        + _moves_for("P2", [0.03] * 8) + _moves_for("P3", [0.03] * 8)
    )
    fair = fm.estimate_fair_moves(moves, _events(["T1", "P1", "P2", "P3"])).set_index("ticker")
    row = fair.loc["T1"]
    assert 2.1 <= row["t_nu"] <= 30.0
    assert 0 < row["t_scale"] < 1.0


def test_sanity_harness_returns_summary(capsys):
    rng = np.random.default_rng(11)
    rows = []
    for i in range(8):
        rows += _moves_for(f"N{i}", list(np.abs(rng.normal(0.04, 0.01, size=8))))
    moves = pd.DataFrame(rows)
    events = _events([f"N{i}" for i in range(8)])
    summary = fm.sanity_harness(moves, events)
    assert summary["n_names"] == 8
    assert 0.2 < summary["median_ratio"] < 5.0
    assert 0.0 <= summary["share_inside_t80"] <= 1.0
    assert "sanity:" in capsys.readouterr().out
