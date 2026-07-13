from datetime import date

import numpy as np
import pandas as pd

from ingest import mentions
from themes import cluster


class _Resp:
    status_code = 200
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


class _Session:
    def __init__(self):
        self.calls = 0
    def get(self, url, params=None, timeout=None):
        self.calls += 1
        page = int(url.rsplit("/", 1)[1])
        if page == 1:
            return _Resp({"pages": 2, "results": [
                {"ticker": "MU", "mentions": 52, "upvotes": 262, "rank": 1, "mentions_24h_ago": 39},
                {"ticker": "SPY", "mentions": 76, "upvotes": 404, "rank": 2, "mentions_24h_ago": 51},
            ]})
        return _Resp({"pages": 2, "results": [
            {"ticker": "POET", "mentions": 9, "upvotes": 30, "rank": 60, "mentions_24h_ago": 2},
        ]})


def test_fetch_apewisdom_pagination():
    df = mentions.fetch_apewisdom(session=_Session())
    assert set(df["ticker"]) == {"MU", "SPY", "POET"}
    assert df.set_index("ticker").loc["MU", "mentions"] == 52


def test_velocity_short_history_flagged():
    today = pd.DataFrame([
        {"ticker": "MU", "mentions": 52, "upvotes": 1, "rank": 1, "mentions_24h_ago": 13},
        {"ticker": "DED", "mentions": 2, "upvotes": 1, "rank": 99, "mentions_24h_ago": 16},
    ])
    hist = today.assign(date="2026-07-12")  # a single day of history
    out = mentions.mention_velocity(hist, today).set_index("ticker")
    assert (out["velocity_mode"] == "short-history").all()
    assert out.loc["MU", "velocity_z"] == np.log2(53 / 14)
    assert out.loc["DED", "velocity_z"] < 0


def test_velocity_zscore_with_enough_history():
    days = pd.date_range("2026-05-01", periods=60).strftime("%Y-%m-%d")
    hist = pd.DataFrame(
        [{"ticker": "MU", "mentions": (10 + i % 3) if i < 30 else 60, "date": d}
         for i, d in enumerate(days)]
    )
    today = pd.DataFrame([{"ticker": "MU", "mentions": 60, "upvotes": 0, "rank": 1,
                           "mentions_24h_ago": 55}])
    out = mentions.mention_velocity(hist, today)
    assert out.iloc[0]["velocity_mode"] == "zscore"
    assert out.iloc[0]["velocity_z"] > 1.0, "recent surge must show a positive z"


def test_praw_inactive_without_creds(monkeypatch):
    for v in mentions.REDDIT_ENV:
        monkeypatch.delenv(v, raising=False)
    assert mentions.fetch_praw_daily_thread().empty


def test_theme_classification_covers_both_cohorts():
    from autopsy.cohorts import load_cohorts

    cohorts = load_cohorts()["cohorts"]
    all_tickers = sorted({t for c in cohorts.values() for t in c["tickers"]})
    themes = cluster.classify(pd.Series(all_tickers))
    assert (themes != "unmapped").all(), (
        f"cohort tickers must all be theme-mapped; missing: "
        f"{[t for t, th in zip(all_tickers, themes) if th == 'unmapped']}"
    )


def test_theme_summary_aggregates():
    m = pd.DataFrame([
        {"ticker": "MU", "mentions": 52, "velocity_z": 1.5},
        {"ticker": "POET", "mentions": 9, "velocity_z": 2.0},
        {"ticker": "ZZZZQ", "mentions": 5, "velocity_z": 0.0},  # unmapped -> excluded
    ])
    agg = cluster.theme_mention_summary(m).set_index("theme")
    assert agg.loc["memory", "mentions"] == 52
    assert agg.loc["optics_networking", "max_velocity_z"] == 2.0
    assert "unmapped" not in agg.index
