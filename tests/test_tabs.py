from datetime import date

import pandas as pd

from dashboard import daily
from tests.test_dashboard import _plan, _scored


def _squeeze():
    return pd.DataFrame(
        [
            {
                "ticker": "HOT", "name": "Hot Co", "sector": "Tech",
                "earnings_date": date(2026, 7, 16), "session": "AMC",
                "float_shares": 50e6, "shares_outstanding": 60e6,
                "inst_pct": 0.35, "insider_pct": 0.10, "retail_pct": 0.55,
                "si_shares": 12e6, "si_pct_float": 0.24, "days_to_cover": 6.0,
                "avg_vol_10d": 8e6, "float_turnover": 0.16, "si_trend": 0.2,
                "si_source": "nasdaq", "squeeze_score": 91.0, "candidate": True,
                "squeeze_risk": True, "structure": "long call",
                "detail": "long 23C @ ask", "entry_side": "debit",
                "entry_price": 80.0, "max_loss": 80.0, "max_gain": float("inf"),
                "strike": 23.0, "legs_json": '[{"action":"BUY","right":"CALL","strike":23.0}]',
                "spot": 20.0, "expiry": "2026-07-17", "implied_move_mid": 0.15,
                "entry_by": date(2026, 7, 16),
            },
            {
                "ticker": "COLD", "name": "Cold Co", "sector": "Tech",
                "earnings_date": date(2026, 7, 17), "session": "BMO",
                "float_shares": 5e9, "shares_outstanding": 5.5e9,
                "inst_pct": 0.80, "insider_pct": 0.01, "retail_pct": 0.19,
                "si_shares": 30e6, "si_pct_float": 0.006, "days_to_cover": 1.0,
                "avg_vol_10d": 30e6, "float_turnover": 0.006, "si_trend": 0.0,
                "si_source": "yahoo", "squeeze_score": 22.0, "candidate": False,
                "squeeze_risk": False, "structure": "watch only", "detail": "",
                "entry_side": "", "entry_price": float("nan"), "max_loss": float("nan"),
                "max_gain": float("nan"), "strike": float("nan"), "legs_json": "",
                "spot": float("nan"), "expiry": "", "implied_move_mid": float("nan"),
                "entry_by": date(2026, 7, 16),
            },
        ]
    )


def test_page_has_three_tabs_with_candidate_count():
    out = daily.render_html(_scored(), date(2026, 7, 12), plan=_plan(), squeeze=_squeeze())
    assert 'data-tab=plan' in out and 'data-tab=squeeze' in out and 'data-tab=positioning' in out
    assert "Squeeze watch (1)" in out
    assert 'id=squeeze hidden' in out, "non-default tabs start hidden"


def test_squeeze_tab_card_contents():
    out = daily.render_squeeze_section(_squeeze())
    assert "BUY 1 × HOT  $23 CALL  exp Fri Jul 17" in out
    assert "24.0% of float" in out
    assert "official Nasdaq settlement" in out
    assert "squeeze score 91/100" in out
    assert "lottery ticket" in out          # honesty stays in the copy
    assert "Place this order on <strong>Thu Jul 16</strong>" in out
    assert "Watch list" in out


def test_squeeze_tab_empty_states():
    out = daily.render_squeeze_section(None)
    assert "No positioning data yet" in out
    no_cands = _squeeze().assign(candidate=False)
    assert "No candidates today" in daily.render_squeeze_section(no_cands)


def test_positioning_tab_table():
    out = daily.render_positioning_section(_squeeze())
    assert "Main St vs Wall St" in out
    assert "class=sortable" in out
    assert "data-s=1" in out                 # sortable headers
    assert "HOT" in out and "COLD" in out
    assert "meterfill" in out                # meters render
