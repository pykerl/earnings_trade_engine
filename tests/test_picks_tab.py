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


def test_live_overlay_appends_without_touching_history():
    data = _day1_data()
    intr = pd.DataFrame({
        "ticker": ["AAA", "CCC"],  # BBB has no bars -> falls back to last close
        "last": [110.0, 9.0],
        "asof": pd.to_datetime(["2026-07-21 18:30:00"]* 2).tz_localize("UTC"),
    })
    data["intraday"] = intr
    nav_live, pos_live, asof = picks_tab.live_overlay(data)
    assert asof is not None
    # official history untouched
    assert len(data["nav"]) == 4 and (data["nav"]["nav"] == 10_000.0).all()
    live = nav_live[nav_live["date"] == date(2026, 7, 21)].set_index("portfolio")
    assert live.loc["John", "nav"] == pytest.approx(50 * 110.0 + 250 * 20.0)
    assert live.loc["PaulMeme", "nav"] == pytest.approx(1000 * 9.0)
    html = picks_tab.render_picks_tab(date(2026, 7, 21), data=data)
    assert "unofficial" in html and "Live 14:30" in html


def test_live_overlay_skipped_once_close_is_official():
    data = _day1_data()
    data["intraday"] = pd.DataFrame({
        "ticker": ["AAA"], "last": [110.0],
        "asof": pd.to_datetime(["2026-07-20 19:30:00"]).tz_localize("UTC"),
    })
    nav_live, _, asof = picks_tab.live_overlay(data)
    assert asof is None
    assert len(nav_live) == len(data["nav"])
