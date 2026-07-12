from datetime import date

import numpy as np
import pandas as pd

from journal import writer as journal_writer
from memos import generator as gen


def _vrow(**over):
    row = {
        "ticker": "TST", "name": "Test Co", "verdict": "buy candidate",
        "market_cap": 8e9, "net_debt": -1e9, "owner_earnings_norm": 1e9,
        "oe_yield": 0.12, "t10": 0.045, "dcf_growth_used": 0.06,
        "value_oe_yield": 12.8e9, "value_dcf": 13.5e9, "value_dcf_low": 11.5e9,
        "value_dcf_high": 15.8e9, "value_epv": 10.0e9, "value_conservative": 10.0e9,
        "implied_growth": 0.021, "margin_of_safety": 0.20,
        "roic_median_10y": 0.21, "roic_latest": 0.23, "roic_trend": 0.002,
        "gross_margin": 0.58, "gm_sigma_10y": 0.015, "gm_trend": 0.001,
        "op_margin": 0.25, "om_sigma_10y": 0.02, "fcf_ni_10y": 0.95,
        "incremental_roic_5y": 0.25, "rev_cagr_10y": 0.07, "rev_cagr_5y": 0.06,
        "rev_consistency": 0.9, "rev_drawdown_2020": -0.05, "nd_ebitda": np.nan,
        "interest_coverage": 30.0, "altman_z_coarse": 6.0, "share_cagr_10y": -0.02,
        "op_income_derived": False, "sbc_fcf_10y": 0.06, "buyback_timing": 0.4,
        "dividend_years_10y": 10, "buyback_years_10y": 10,
        "owner_earnings": 1.05e9, "owner_earnings_3y_avg": 1e9,
        "maint_capex_proxy": "min(depreciation & amortization, capex)",
        "moat_flag": True, "eject": False, "demote_count": 0,
        "demote_reasons": "", "eject_reasons": "",
        "needs_human_review": "substitution risk unassessed",
        "rank_score": 0.20, "years_of_data": 11, "latest_fy_end": "2025-12-31",
    }
    row.update(over)
    return pd.Series(row)


def _events():
    return pd.DataFrame(
        [{"ticker": "TST", "earnings_date": date(2026, 7, 16), "session": "AMC"}]
    )


def test_render_memo_contains_all_eight_sections():
    md = gen.render_memo(
        _vrow(), {"business_excerpt": "We sell widgets.", "mda_excerpt": "Margins were stable."},
        insider_line="2 buys", guru_line="Berkshire Hathaway: $1.20B",
        events=_events(), memo_date=date(2026, 7, 12),
    )
    for heading in [
        "## 1. Business in two sentences", "## 2. Moat evidence",
        "## 3. Management & capital allocation", "## 4. Owner earnings",
        "## 5. What the market is missing", "## 6. Bear case & pre-mortem",
        "## 7. Earnings-season note", "## 8. Verdict",
    ]:
        assert heading in md
    assert "[FOR HUMAN REVIEW]" in md
    assert "min(depreciation & amortization, capex)" in md
    assert "We sell widgets." in md
    assert "Reports 2026-07-16" in md
    assert "instead of an index fund" in md
    assert "BUY CANDIDATE" in md


def test_thesis_driver_epv_branch():
    t = gen.thesis_driver(_vrow(market_cap=8e9, value_epv=10e9))
    assert "BELOW the zero-growth EPV" in t
    t2 = gen.thesis_driver(_vrow(market_cap=12e9, value_epv=10e9, implied_growth=0.02))
    assert "pricing 2.0%/yr growth" in t2 and "delivered 7.0%/yr" in t2


def test_write_memo_never_overwrites(tmp_path, monkeypatch):
    from common import config

    monkeypatch.setattr(config, "MEMOS_DIR", tmp_path)
    p1 = gen.write_memo("TST", "first", date(2026, 7, 12))
    p2 = gen.write_memo("TST", "second", date(2026, 7, 12))
    assert p1 != p2
    assert open(p1).read() == "first" and open(p2).read() == "second"


def test_extract_item_prefers_second_occurrence():
    text = (
        "TABLE OF CONTENTS Item 1. Business Item 7. MD&A ... "
        "Item 1. Business We make widgets in 40 countries. Item 1A. Risk Factors ..."
    )
    got = gen.extract_item(text, "1", ["1A", "1B", "2"])
    assert "We make widgets" in got and "TABLE OF" not in got


def test_journal_register_append_only(tmp_path):
    path = tmp_path / "expectations.csv"
    rows = [journal_writer.expectations_row(_vrow(), "epv thesis", date(2026, 7, 12))]
    assert journal_writer.register(rows, path=path) == 1
    assert journal_writer.register(rows, path=path) == 0, "same (ticker, date) never re-registered"
    saved = pd.read_csv(path)
    assert len(saved) == 1
    assert saved.loc[0, "exp_gm_low"] == 0.55 and saved.loc[0, "exp_gm_high"] == 0.61
    assert bool(saved.loc[0, "exp_buybacks_continue"]) is True
