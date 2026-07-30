from datetime import date

import pandas as pd

from picks import events

RULES = events_RULES = {
    "portfolios": {
        "John": {"tickers": ["AAA", "BBB"]},
        "PaulMeme": {"tickers": ["CCC"]},
    },
    "benchmarks": ["SPY"],
    "rules": {"inception_earliest": "2026-07-20", "end_date": "2026-09-04"},
}


def test_resolve_dates_statuses(monkeypatch):
    yf = pd.DataFrame([
        {"ticker": "AAA", "earnings_date": date(2026, 8, 4), "session": "AMC"},
        {"ticker": "BBB", "earnings_date": date(2026, 8, 12), "session": "BMO"},
        # CCC missing from yfinance entirely -> unresolved
    ])
    nasdaq = pd.DataFrame([
        {"ticker": "AAA", "earnings_date": date(2026, 8, 4), "session": "AMC"},   # confirms
        {"ticker": "BBB", "earnings_date": date(2026, 8, 13), "session": "BMO"},  # conflicts
    ])
    monkeypatch.setattr(events, "_yf_events", lambda *a, **k: yf)
    monkeypatch.setattr(events, "_nasdaq_events", lambda *a, **k: nasdaq)
    monkeypatch.setattr(events.cal, "fetch_finnhub_calendar",
                        lambda **k: pd.DataFrame(columns=["ticker", "earnings_date", "session"]))

    out = events.resolve_dates(RULES, today=date(2026, 7, 21))
    assert len(out) == 3  # every pick keeps a row
    by = out.set_index("ticker")
    assert by.loc["AAA", "status"] == "confirmed"
    assert by.loc["BBB", "status"] == "conflict"
    assert "nasdaq=2026-08-13" in by.loc["BBB", "sources"]
    assert by.loc["CCC", "status"] == "unresolved"
    assert pd.isna(by.loc["CCC", "earnings_date"])


def test_t1_date_skips_weekend():
    assert events.t1_date(date(2026, 8, 4)) == date(2026, 8, 3)   # Tue -> Mon
    assert events.t1_date(date(2026, 8, 3)) == date(2026, 7, 31)  # Mon -> Fri


def test_t1_freeze_only_at_t1_and_first_write_wins(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "PICKS_PREDICTIONS_CSV", tmp_path / "j.csv")
    monkeypatch.setattr(events, "_fair_move_lookup", lambda: pd.DataFrame(
        [{"ticker": "AAA", "fair_move": 0.05, "ci_low": 0.03, "ci_high": 0.08, "n_events": 12}]))

    def fake_chain(ticker, event_date, session):
        return ({"ticker": ticker, "earnings_date": event_date, "session": session,
                 "spot": 100.0, "expiry": "2026-08-07", "atm_strike": 100.0,
                 "straddle_bid": 6.0, "straddle_mid": 6.5, "straddle_ask": 7.0,
                 "implied_move_bid": 0.06, "implied_move_mid": 0.065,
                 "implied_move_ask": 0.07}, None)

    monkeypatch.setattr("ingest.chains.fetch_event_chain", fake_chain)

    evs = pd.DataFrame([
        {"ticker": "AAA", "portfolio": "John", "earnings_date": date(2026, 8, 4),
         "session": "AMC", "status": "confirmed", "sources": "yfinance,nasdaq"},
        {"ticker": "BBB", "portfolio": "John", "earnings_date": date(2026, 8, 12),
         "session": "BMO", "status": "confirmed", "sources": "yfinance,nasdaq"},
        {"ticker": "CCC", "portfolio": "PaulMeme", "earnings_date": pd.NaT,
         "session": "unknown", "status": "unresolved", "sources": ""},
    ])

    # 2026-08-03 is T-1 for AAA only; BBB far out, CCC undated
    reg = events.t1_freeze(evs, today=date(2026, 8, 3))
    assert list(reg["ticker"]) == ["AAA"]
    row = reg.iloc[0]
    assert row["implied_move_mid"] == 0.065
    assert row["fair_move"] == 0.05
    assert row["portfolio"] == "John"

    # rerun same day: frozen, nothing new
    assert events.t1_freeze(evs, today=date(2026, 8, 3)).empty
    journal = pd.read_csv(tmp_path / "j.csv")
    assert len(journal) == 1

    # a run ON the event day never writes (journal refuses ev <= today)
    assert events.t1_freeze(evs, today=date(2026, 8, 4)).empty
    assert len(pd.read_csv(tmp_path / "j.csv")) == 1


def test_reported_names_keep_their_past_date(tmp_path, monkeypatch):
    monkeypatch.setattr(events, "PICKS_EVENTS_PARQUET", tmp_path / "ev.parquet")
    monkeypatch.setattr(events, "PICKS_PREDICTIONS_CSV", tmp_path / "j.csv")
    monkeypatch.setattr(events, "resolve_dates", lambda rules, today=None: pd.DataFrame([
        {"ticker": "AAA", "portfolio": "John", "earnings_date": pd.NaT,
         "session": "unknown", "status": "unresolved", "sources": ""},
        {"ticker": "BBB", "portfolio": "John", "earnings_date": date(2026, 8, 12),
         "session": "BMO", "status": "confirmed", "sources": "yfinance,nasdaq"},
        {"ticker": "CCC", "portfolio": "PaulMeme", "earnings_date": date(2026, 8, 26),
         "session": "AMC", "status": "confirmed", "sources": "yfinance,nasdaq"},
    ]))
    monkeypatch.setattr("picks.nav.load_rules", lambda: events_RULES)
    prior = pd.DataFrame([
        {"ticker": "AAA", "portfolio": "John", "earnings_date": date(2026, 7, 29),
         "session": "AMC", "status": "confirmed", "sources": "yfinance,nasdaq"},
        {"ticker": "BBB", "portfolio": "John", "earnings_date": date(2026, 8, 12),
         "session": "BMO", "status": "confirmed", "sources": "yfinance,nasdaq"},
        {"ticker": "CCC", "portfolio": "PaulMeme", "earnings_date": date(2026, 8, 26),
         "session": "AMC", "status": "confirmed", "sources": "yfinance,nasdaq"},
    ])
    prior.to_parquet(tmp_path / "ev.parquet")
    out = events.run(today=date(2026, 7, 30)).set_index("ticker")
    assert out.loc["AAA", "status"] == "reported"
    assert pd.Timestamp(out.loc["AAA", "earnings_date"]).date() == date(2026, 7, 29)
