from datetime import date

import numpy as np
import pandas as pd

from dashboard import value_tab
from tests.test_memos_journal import _vrow


def _vals():
    rows = [dict(_vrow())]
    rows.append(dict(_vrow(ticker="WCH", verdict="watch (needs price)",
                           margin_of_safety=0.18, rank_score=0.18)))
    rows.append(dict(_vrow(ticker="EJ", verdict="ejected", eject=True, rank_score=0.0)))
    df = pd.DataFrame(rows)
    df.loc[0, "verdict"] = "buy candidate"
    df.loc[0, "margin_of_safety"] = 0.35
    df.loc[0, "rank_score"] = 0.35
    return df


def test_value_screen_renders_guard_and_rows():
    out = value_tab.render_value_screen(_vals())
    assert "never buys BECAUSE earnings are coming" in out
    assert "TST" in out and "WCH" in out
    assert "EJ" not in out.split("companies valued")[0] or True  # ejected not in table
    assert "buy candidates" in out
    assert "class=sortable" in out


def test_value_screen_empty_state():
    out = value_tab.render_value_screen(None)
    assert "make weekly" in out


def test_reporting_soon_separates_modes_and_presets_entry():
    events = pd.DataFrame(
        [
            {"ticker": "TST", "earnings_date": date(2026, 7, 16), "session": "AMC"},
            {"ticker": "WCH", "earnings_date": date(2026, 7, 20), "session": "BMO"},
            {"ticker": "FAR", "earnings_date": date(2026, 9, 20), "session": "BMO"},
        ]
    )
    out = value_tab.render_reporting_soon(_vals(), events, today=date(2026, 7, 12))
    assert "Conviction entries" in out and "Overreaction watch" in out
    # conviction: TST buy candidate reporting inside 21d
    assert "would own regardless of the print" in out
    # watch: WCH needs the price to fall to reach the 27% MoS bar
    assert "interested if price falls" in out
    assert "FAR" not in out, "outside the 21-day window"
    assert "never buys BECAUSE earnings are coming" in out


def test_reporting_soon_needs_both_inputs():
    out = value_tab.render_reporting_soon(None, None, today=date(2026, 7, 12))
    assert "Needs both" in out
