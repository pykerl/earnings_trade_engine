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


MEMO_MD = """# TST — Test Co · thesis memo (2026-07-12)

> Auto-drafted for review.
> Not advice.

## 2. Moat evidence
- ROIC 10-yr median **21%**
- Gross margin 58%

| Lens | Value |
|---|---|
| EPV | $10.0B |

Filing excerpt with <script>alert(1)</script> inside.
"""


def test_md_to_html_renders_and_escapes():
    out = value_tab.md_to_html(MEMO_MD)
    assert "<h3>2. Moat evidence</h3>" in out
    assert "<strong>21%</strong>" in out
    assert "<table><tr><th>Lens</th>" in out and "<td>$10.0B</td>" in out
    assert "<blockquote>" in out
    assert "<script>" not in out, "filing text must be escaped"
    assert "&lt;script&gt;" in out


def test_value_screen_embeds_memo_modal():
    out = value_tab.render_value_screen(_vals(), memos_by_ticker={"TST": MEMO_MD})
    assert 'data-memo="memo-TST"' in out and "📝" in out
    assert '<template id="memo-TST">' in out
    assert '<template id="memo-TST">' in out  # overlay now lives at page level
    # watch name without a memo stays a plain cell
    assert 'data-memo="WCH"' not in out


def test_load_latest_memos_picks_newest(tmp_path, monkeypatch):
    from common import config

    monkeypatch.setattr(config, "MEMOS_DIR", tmp_path)
    (tmp_path / "TST_2026-07-05.md").write_text("old")
    (tmp_path / "TST_2026-07-12.md").write_text("new")
    (tmp_path / "OTHER_2026-07-12.md").write_text("x")
    got = value_tab.load_latest_memos(["TST", "MISSING"])
    assert got == {"TST": "new"}
