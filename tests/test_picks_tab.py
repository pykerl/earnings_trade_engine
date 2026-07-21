from datetime import date

import pandas as pd
import pytest

from dashboard import picks_tab

RULES = {
    "portfolios": {
        "John": {"allocation_per_name": 5000.0, "tickers": ["AAA", "BBB"]},
        "PaulMeme": {"allocation_per_name": 10000.0, "tickers": ["CCC"]},
    },
    "benchmarks": ["SPY", "QQQ"],
    "rules": {"inception_earliest": "2026-07-20", "end_date": "2026-09-04"},
}


def _day1_data():
    d = date(2026, 7, 20)
    nav = pd.DataFrame([
        {"date": d, "portfolio": p, "nav": 10_000.0, "cash": 0.0}
        for p in ["John", "PaulMeme", "BM:SPY", "BM:QQQ"]
    ])
    inception = pd.DataFrame([
        {"portfolio": "John", "ticker": "AAA", "inception_date": "2026-07-20",
         "entry_close": 100.0, "allocation": 5000.0, "shares": 50.0},
        {"portfolio": "John", "ticker": "BBB", "inception_date": "2026-07-20",
         "entry_close": 20.0, "allocation": 5000.0, "shares": 250.0},
        {"portfolio": "PaulMeme", "ticker": "CCC", "inception_date": "2026-07-20",
         "entry_close": 10.0, "allocation": 10000.0, "shares": 1000.0},
    ])
    positions = pd.DataFrame([
        {"date": d, "portfolio": "John", "ticker": "AAA", "shares": 50.0,
         "close": 100.0, "value": 5000.0, "cash": 0.0, "entry_close": 100.0},
        {"date": d, "portfolio": "John", "ticker": "BBB", "shares": 250.0,
         "close": 20.0, "value": 5000.0, "cash": 0.0, "entry_close": 20.0},
        {"date": d, "portfolio": "PaulMeme", "ticker": "CCC", "shares": 1000.0,
         "close": 10.0, "value": 10000.0, "cash": 0.0, "entry_close": 10.0},
    ])
    events = pd.DataFrame([
        {"portfolio": "John", "ticker": "AAA", "earnings_date": date(2026, 8, 4),
         "session": "AMC", "status": "confirmed", "sources": "yfinance,nasdaq"},
        {"portfolio": "John", "ticker": "BBB", "earnings_date": pd.NaT,
         "session": "unknown", "status": "unresolved", "sources": ""},
        {"portfolio": "PaulMeme", "ticker": "CCC", "earnings_date": date(2026, 8, 26),
         "session": "AMC", "status": "conflict", "sources": "yfinance vs nasdaq=2026-08-25"},
    ])
    return {"rules": RULES, "nav": nav, "inception": inception, "positions": positions,
            "events": events, "enriched": None, "journal": None}


def test_day1_single_point_renders():
    html = picks_tab.render_picks_tab(date(2026, 7, 20), data=_day1_data())
    assert "NAV race" in html and "<svg" in html
    assert html.count("$10,000") >= 4          # scoreboard tiles
    assert "AAA" in html and "CCC" in html     # holdings + flags
    assert "n/a" in html                       # enrichment absent -> degrades
    assert "unresolved" in html                # missing date visible, not dropped
    assert "⚠︎" in html                        # conflict marker
    assert "n/a (&lt;5d)" in html              # risk stats need history
    assert "β×QQQ" in html or "beta" in html.lower()


def test_no_nav_yet_renders_placeholder():
    html = picks_tab.render_picks_tab(
        date(2026, 7, 20),
        data={"rules": RULES, "nav": None, "inception": None, "positions": None,
              "events": None, "enriched": None, "journal": None},
    )
    assert "No NAV history yet" in html


def test_leaderboard_frame_ranks_by_nav():
    data = _day1_data()
    nav = data["nav"].copy()
    nav.loc[nav["portfolio"] == "PaulMeme", "nav"] = 10_500.0
    lb = picks_tab.leaderboard_frame(nav)
    assert lb.iloc[0]["portfolio"] == "PaulMeme"
    assert lb.iloc[0]["rank"] == 1
    assert lb.iloc[0]["total_return"] == pytest.approx(0.05)
