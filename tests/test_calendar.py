from datetime import date

import pandas as pd

from ingest import calendar as cal


def _ev(ticker, d, session):
    return {"ticker": ticker, "earnings_date": d, "session": session}


def test_reconcile_confirms_drops_and_flags():
    d1, d2 = date(2026, 7, 14), date(2026, 7, 15)
    yf = pd.DataFrame(
        [
            _ev("JPM", d1, "BMO"),      # confirmed by nasdaq, sessions agree
            _ev("WFC", d1, "unknown"),  # confirmed, session comes from nasdaq
            _ev("BAD", d1, "AMC"),      # nasdaq says a different date -> drop
            _ev("SOLO", d2, "AMC"),     # nobody else lists it -> single_source
            _ev("MIX", d1, "BMO"),      # nasdaq agrees on date, disagrees on session
        ]
    )
    nasdaq = pd.DataFrame(
        [
            _ev("JPM", d1, "BMO"),
            _ev("WFC", d1, "BMO"),
            _ev("BAD", d2, "AMC"),
            _ev("MIX", d1, "AMC"),
        ]
    )
    kept, dropped = cal.reconcile(yf, {"nasdaq": nasdaq, "finnhub": pd.DataFrame()})

    kept = kept.set_index("ticker")
    assert list(dropped["ticker"]) == ["BAD"]
    assert kept.loc["JPM", "source_agreement"] == "confirmed"
    assert kept.loc["JPM", "session"] == "BMO"
    assert kept.loc["WFC", "session"] == "BMO"  # unknown + BMO -> BMO
    assert kept.loc["SOLO", "source_agreement"] == "single_source"
    assert kept.loc["MIX", "session"] == "unknown"  # BMO vs AMC -> unknown


def test_reconcile_handles_duplicate_rows_in_source():
    d1 = date(2026, 7, 14)
    yf = pd.DataFrame([_ev("JPM", d1, "BMO")])
    nasdaq = pd.DataFrame([_ev("JPM", d1, "BMO"), _ev("JPM", d1, "unknown")])
    kept, dropped = cal.reconcile(yf, {"nasdaq": nasdaq})
    assert len(kept) == 1 and len(dropped) == 0


def test_session_from_hour():
    assert cal._session_from_hour(pd.Timestamp("2026-07-14 08:00")) == "BMO"
    assert cal._session_from_hour(pd.Timestamp("2026-07-14 16:30")) == "AMC"
    assert cal._session_from_hour(pd.Timestamp("2026-07-14 12:00")) == "unknown"


def test_nasdaq_session_mapping():
    assert cal._nasdaq_session("time-pre-market") == "BMO"
    assert cal._nasdaq_session("time-after-hours") == "AMC"
    assert cal._nasdaq_session("time-not-supplied") == "unknown"


def test_finnhub_returns_empty_without_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    df = cal.fetch_finnhub_calendar()
    assert df.empty and list(df.columns) == ["ticker", "earnings_date", "session"]
