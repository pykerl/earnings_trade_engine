from datetime import date

import numpy as np
import pandas as pd
import pytest

from picks import nav


RULES = {
    "portfolios": {
        "John": {"capital": 10000.0, "allocation_per_name": 5000.0, "tickers": ["AAA", "BBB"]},
        "PaulMeme": {"capital": 10000.0, "allocation_per_name": 10000.0, "tickers": ["CCC"]},
    },
    "benchmarks": ["SPY"],
    "rules": {"inception_earliest": "2026-07-20", "end_date": "2026-09-04"},
}


def _frames():
    days = pd.bdate_range("2026-07-20", "2026-07-24")
    closes = pd.DataFrame(
        {"AAA": [100.0, 102.0, 104.0, 50.0, 51.0],
         "BBB": [20.0, 21.0, 20.5, 20.0, 22.0],
         "CCC": [10.0, 11.0, 12.0, 11.5, 13.0],
         "SPY": [500.0, 501.0, 502.0, 503.0, 504.0]},
        index=days,
    )
    dividends = pd.DataFrame(0.0, index=days, columns=closes.columns)
    dividends.loc[days[2], "BBB"] = 0.50  # ex-date div on day 3
    splits = pd.DataFrame(0.0, index=days, columns=closes.columns)
    splits.loc[days[3], "AAA"] = 2.0  # 2:1 split, close halves same day
    return closes, dividends, splits


def test_inception_shares_and_benchmarks():
    closes, _, _ = _frames()
    inc = nav.build_inception(RULES, closes)
    assert len(inc) == 4  # 3 names + 1 benchmark
    aaa = inc[inc["ticker"] == "AAA"].iloc[0]
    assert aaa["shares"] == pytest.approx(50.0)  # 5000 / 100
    bm = inc[inc["portfolio"] == "BM:SPY"].iloc[0]
    assert bm["shares"] == pytest.approx(20.0)  # 10000 / 500
    assert (inc["inception_date"] == "2026-07-20").all()


def test_split_and_dividend_handling(tmp_path, monkeypatch):
    monkeypatch.setattr(nav, "ACTIONS_CSV", tmp_path / "actions.csv")
    closes, dividends, splits = _frames()
    inc = nav.build_inception(RULES, closes)
    pos = nav.compute_positions(inc, closes, dividends, splits)

    # AAA split 2:1 on day 4: shares double, value continuous
    aaa = pos[pos["ticker"] == "AAA"].sort_values("date")
    assert aaa.iloc[2]["shares"] == pytest.approx(50.0)
    assert aaa.iloc[3]["shares"] == pytest.approx(100.0)
    assert aaa.iloc[3]["value"] == pytest.approx(100.0 * 50.0)

    # BBB dividend: cash = shares * 0.50 from ex-date onward
    bbb = pos[pos["ticker"] == "BBB"].sort_values("date")
    sh = 5000.0 / 20.0
    assert bbb.iloc[1]["cash"] == pytest.approx(0.0)
    assert bbb.iloc[2]["cash"] == pytest.approx(sh * 0.5)
    assert bbb.iloc[4]["cash"] == pytest.approx(sh * 0.5)

    actions = pd.read_csv(tmp_path / "actions.csv")
    assert set(actions["action"]) == {"split", "dividend"}

    # NAV includes dividend cash
    navdf = nav.compute_nav(pos)
    john_last = navdf[(navdf["portfolio"] == "John")].sort_values("date").iloc[-1]
    expected = 100.0 * 51.0 + sh * 22.0 + sh * 0.5
    assert john_last["nav"] == pytest.approx(expected)


def test_inception_immutable(tmp_path, monkeypatch):
    monkeypatch.setattr(nav, "INCEPTION_PARQUET", tmp_path / "inc.parquet")
    monkeypatch.setattr(nav, "INCEPTION_CSV", tmp_path / "inc.csv")
    closes, _, _ = _frames()
    first = nav.load_or_freeze_inception(RULES, closes)
    # identical re-run: fine, returns frozen
    again = nav.load_or_freeze_inception(RULES, closes)
    pd.testing.assert_frame_equal(first, again)
    # restated entry price -> assert-fail
    tampered = closes.copy()
    tampered.loc[tampered.index[0], "AAA"] = 999.0
    with pytest.raises(AssertionError, match="immutable inception"):
        nav.load_or_freeze_inception(RULES, tampered)
    # changed universe -> assert-fail
    bigger = dict(RULES, portfolios={
        **RULES["portfolios"],
        "John": {"capital": 10000.0, "allocation_per_name": 5000.0,
                 "tickers": ["AAA", "BBB", "CCC"]},
    })
    with pytest.raises(AssertionError, match="universe changed"):
        nav.load_or_freeze_inception(bigger, closes)


def test_nav_append_only(tmp_path, monkeypatch):
    monkeypatch.setattr(nav, "NAV_PARQUET", tmp_path / "nav.parquet")
    base = pd.DataFrame({
        "date": [date(2026, 7, 20), date(2026, 7, 21)],
        "portfolio": ["John", "John"],
        "nav": [10000.0, 10100.0], "cash": [0.0, 0.0],
    })
    nav.append_only_write(base)
    # appending a new date with history intact: ok
    grown = pd.concat([base, pd.DataFrame({
        "date": [date(2026, 7, 22)], "portfolio": ["John"],
        "nav": [10200.0], "cash": [0.0]})], ignore_index=True)
    nav.append_only_write(grown)
    # small vendor restatement: frozen row kept as first written, no error
    nudged = grown.copy()
    nudged.loc[0, "nav"] = 10000.09
    out = nav.append_only_write(nudged)
    assert out[(out["date"] == date(2026, 7, 20)) & (out["portfolio"] == "John")][
        "nav"].iloc[0] == pytest.approx(10000.0)
    # large drift is a real defect, not a restatement -> assert-fail
    bad = grown.copy()
    bad.loc[0, "nav"] = 9000.0
    with pytest.raises(AssertionError, match="vendor restatement"):
        nav.append_only_write(bad)
