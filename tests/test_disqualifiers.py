from datetime import date

import numpy as np
import pandas as pd

from features import disqualifiers as dq
from tests.test_quality import _annual


def _qrow(**over):
    base = {
        "ticker": "TST", "fcf_ni_10y": 0.95, "nd_ebitda": 1.0,
        "interest_coverage": 20.0, "share_cagr_10y": -0.01,
        "sbc_fcf_10y": 0.05, "altman_z_coarse": 5.0,
    }
    base.update(over)
    return pd.Series(base)


def test_clean_compounder_raises_no_quant_flags():
    flags = dq.quant_flags(_qrow(), _annual())
    assert not any(flags.values())


def test_leverage_and_dilution_flags():
    assert dq.quant_flags(_qrow(nd_ebitda=3.5), _annual())["leverage"]
    assert dq.quant_flags(_qrow(interest_coverage=2.0), _annual())["leverage"]
    assert dq.quant_flags(_qrow(share_cagr_10y=0.03), _annual())["dilution"]
    assert dq.quant_flags(_qrow(sbc_fcf_10y=0.30), _annual())["dilution"]


def test_structural_decline_needs_no_fcf_offset():
    df = _annual()
    # revenue falls for the last 3 years; FCF falls with it
    df.loc[df.index[-3:], "revenue"] = [900.0, 850.0, 800.0]
    df.loc[df.index[-3:], "cfo"] = [100.0, 90.0, 80.0]
    df.loc[df.index[-3:], "capex"] = [50.0, 50.0, 50.0]
    flags = dq.quant_flags(_qrow(), df)
    assert flags["structural_decline"]


def test_accruals_divergence_flag():
    df = _annual()
    # NI marches up while CFO stagnates
    df["net_income"] = np.linspace(100, 200, len(df))
    df["cfo"] = 120.0
    flags = dq.quant_flags(_qrow(), df)
    assert flags["accruals"]
    assert dq.quant_flags(_qrow(fcf_ni_10y=0.4), _annual())["accruals"]


def test_filing_record_flags_from_submissions():
    subs = {
        "filings": {
            "recent": {
                "form": ["10-K", "NT 10-Q", "8-K", "8-K", "8-K"],
                "filingDate": ["2026-02-01", "2025-11-10", "2025-06-01", "2024-03-01", "2020-01-01"],
                "items": ["", "", "4.01", "4.02,9.01", "4.02"],
            }
        }
    }
    flags = dq.filing_record_flags(subs, today=date(2026, 7, 12))
    assert flags == {"late_filing": True, "auditor_change": True, "restatement": True}
    # the 2020 item 4.02 is outside the 3-year window
    old_only = {
        "filings": {"recent": {"form": ["8-K"], "filingDate": ["2020-01-01"], "items": ["4.02"]}}
    }
    assert not any(dq.filing_record_flags(old_only, today=date(2026, 7, 12)).values())


def test_combine_severity_and_human_review():
    quant = {"structural_decline": True, "leverage": False, "dilution": True,
             "accruals": False, "altman_distress": False}
    record = {"late_filing": False, "auditor_change": True, "restatement": False}
    out = dq.combine_flags(quant, record, going_concern=False)
    assert not out["eject"]
    assert out["demote_count"] == 3
    assert "substitution risk unassessed" in out["needs_human_review"]

    out2 = dq.combine_flags(quant, record, going_concern=True)
    assert out2["eject"] and "going_concern" in out2["eject_reasons"]
    assert "read the opinion" in out2["needs_human_review"]
