from datetime import date

import numpy as np
import pandas as pd
import pytest

from gates import growth_gates as gg
from positions import construct
from tests.test_quality import _annual


def test_constraint_map_flattens_with_evidence_counts():
    cands = gg.candidate_table(gg.load_constraint_map())
    assert len(cands) > 10
    assert (cands["n_evidence"] >= 2).all(), "every shipped node carries >=2 dated items"
    powl = cands[cands["ticker"] == "POWL"].iloc[0]
    assert powl["kind"] == "pure_play" and powl["theme"] == "ai_dc_power"


def test_evidence_gate_blocks_needs_evidence():
    row = pd.Series({"n_evidence": 3, "needs_evidence": False})
    assert gg.evidence_gate(row)
    assert not gg.evidence_gate(pd.Series({"n_evidence": 1, "needs_evidence": False}))
    assert not gg.evidence_gate(pd.Series({"n_evidence": 3, "needs_evidence": True}))


def test_quant_gates_on_healthy_grower():
    q = gg.quant_gates(_annual(growth=0.25))
    assert q["gate_runway"] and q["runway_quarters"] == 99.0  # FCF positive
    assert q["gate_rule40"], f"25% growth + 18% FCF margin must pass: {q['rule_of_40']}"
    assert q["gate_dilution"] and q["gate_gm_trend"] and q["gate_leverage"]


def test_quant_gates_flag_burner_with_short_runway():
    df = _annual()
    df["cfo"] = -df["revenue"] * 0.10          # burning cash
    df["capex"] = df["revenue"] * 0.05
    df["cash"] = df["revenue"] * 0.10           # tiny cash pile
    q = gg.quant_gates(df)
    assert not q["gate_runway"]
    assert q["runway_quarters"] < 8


def test_quant_gates_flag_serial_diluter():
    df = _annual()
    df["shares_diluted"] = 1000 * (1.08) ** np.arange(len(df))  # +8%/yr
    q = gg.quant_gates(df)
    assert not q["gate_dilution"]


def _gates_df():
    base = {
        "name": "X", "exposure": "e", "listing": "US", "confidence": "high",
        "n_evidence": 3, "needs_evidence": False, "capacity_watch": "w",
        "edgar_data": True, "gates_passed": True, "gate_notes": "all pass",
        "needs_human_review": True,
    }
    return pd.DataFrame([
        dict(base, ticker="POWL", node="dc_power", theme="ai_dc_power",
             kind="pure_play", crowded_names="GEV,VST"),
        dict(base, ticker="MYRG", node="dc_power", theme="ai_dc_power",
             kind="pure_play", crowded_names="GEV,VST"),
        dict(base, ticker="HUBB", node="dc_power", theme="ai_dc_power",
             kind="diversified", crowded_names="GEV,VST"),
        dict(base, ticker="COHR", node="optics_interconnect", theme="optics_networking",
             kind="pure_play", crowded_names="POET,LITE"),
        dict(base, ticker="MOD", node="dc_cooling", theme="ai_dc_cooling",
             kind="pure_play", crowded_names="VRT"),
        dict(base, ticker="CAMT", node="memory_hbm", theme="memory",
             kind="pure_play", crowded_names="MU"),
        dict(base, ticker="CROWDED", node="memory_hbm", theme="memory",
             kind="pure_play", crowded_names="MU"),
        dict(base, ticker="FAILED", node="dc_power", theme="ai_dc_power",
             kind="pure_play", crowded_names="GEV", gates_passed=False),
    ])


def _mentions():
    return pd.DataFrame([
        {"ticker": "CROWDED", "mentions": 300, "velocity_z": 2.5, "velocity_mode": "zscore"},
        {"ticker": "POWL", "mentions": 2, "velocity_z": -0.2, "velocity_mode": "zscore"},
    ])


def test_build_ideas_portfolio_rules():
    ideas, opts = construct.build_ideas(_gates_df(), _mentions(), positioning=None)
    # crowding excludes CROWDED (z=2.5); gates exclude FAILED
    assert "CROWDED" not in set(ideas["ticker"])
    assert "FAILED" not in set(ideas["ticker"])
    # max 2 per theme
    assert (ideas.groupby("theme").size() <= construct.MAX_PER_THEME).all()
    # max 3 themes
    assert ideas["theme"].nunique() <= construct.MAX_THEMES
    # pure plays outrank diversified within the same node
    powl = ideas[ideas["ticker"] == "POWL"].iloc[0]
    assert powl["max_position_dollars"] == pytest.approx(500.0)
    assert "GEV" in powl["barbell_against"]
    # options sleeve carries the crowded first-order names
    assert {"GEV", "VST", "POET", "MU"} <= set(opts["ticker"])
    assert (opts["sleeve"] == "options").all()


def test_reddit_tab_renders():
    from dashboard.reddit_tab import render_reddit_tab

    ideas, _ = construct.build_ideas(_gates_df(), _mentions(), positioning=None)
    html_out = render_reddit_tab(
        ideas, _gates_df(), theme_summary=None,
        memos_by_ticker={"POWL": "# POWL memo\n\n- test"},
        autopsy_summary="2026 index +31.7% vs SPY 11.1% — beta, concentration.",
    )
    assert "Reddit Suggestions" in html_out
    assert "never a buy signal" in html_out
    assert 'data-memo="gmemo-POWL"' in html_out
    assert "barbell vs GEV" in html_out
    assert "options_sleeve.csv" in html_out


def test_reddit_tab_empty_state():
    from dashboard.reddit_tab import render_reddit_tab

    out = render_reddit_tab(None, None, None)
    assert "make ideas" in out
