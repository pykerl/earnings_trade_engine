import numpy as np
import pandas as pd

from ingest import positioning as pos


NASDAQ_PAYLOAD = {
    "data": {
        "shortInterestTable": {
            "rows": [
                {"settlementDate": "06/30/2026", "interest": "127,787,110",
                 "avgDailyShareVolume": "127,904,196", "daysToCover": 1.0},
                {"settlementDate": "06/15/2026", "interest": "143,868,544",
                 "avgDailyShareVolume": "131,318,405", "daysToCover": 1.0956},
            ]
        }
    }
}


def test_parse_nasdaq_si_latest_and_trend():
    out = pos.parse_nasdaq_si(NASDAQ_PAYLOAD)
    assert out["si_shares"] == 127_787_110
    assert out["days_to_cover"] == 1.0
    # shorts covered between settlements -> negative trend
    assert out["si_trend"] < 0
    assert round(out["si_trend"], 4) == round(127_787_110 / 143_868_544 - 1, 4)


def test_parse_nasdaq_si_rejects_nyse_response():
    assert pos.parse_nasdaq_si({"data": None}) is None
    assert pos.parse_nasdaq_si({"data": {"shortInterestTable": {"rows": []}}}) is None


class _Resp:
    status_code = 200
    def __init__(self, payload):
        self._p = payload
    def json(self):
        return self._p


class _Session:
    def get(self, url, params=None, timeout=None):
        if "INTC" in url:
            return _Resp(NASDAQ_PAYLOAD)
        return _Resp({"data": None, "message": "not available"})


def test_build_positioning_merges_and_derives(monkeypatch):
    def fake_yf(ticker):
        base = {
            "ticker": ticker, "float_shares": 1_000_000_000.0,
            "shares_outstanding": 1_100_000_000.0, "inst_pct": 0.65,
            "insider_pct": 0.05, "si_shares": 20_000_000.0,
            "si_pct_float": 0.02, "days_to_cover": 1.5,
            "avg_vol_10d": 50_000_000.0, "retail_pct": float("nan"),
            "float_turnover": float("nan"), "si_trend": float("nan"),
            "si_source": "yahoo",
        }
        return base

    monkeypatch.setattr(pos, "fetch_yf_positioning", fake_yf)
    df = pos.build_positioning(["INTC", "BAC"], nasdaq_session=_Session()).set_index("ticker")

    # INTC upgraded to official Nasdaq settlement figures
    assert df.loc["INTC", "si_source"] == "nasdaq"
    assert df.loc["INTC", "si_shares"] == 127_787_110
    assert df.loc["INTC", "si_pct_float"] == 127_787_110 / 1_000_000_000
    assert df.loc["INTC", "si_trend"] < 0
    # BAC (NYSE) keeps Yahoo numbers
    assert df.loc["BAC", "si_source"] == "yahoo"
    assert df.loc["BAC", "si_pct_float"] == 0.02
    # derived fields
    assert df.loc["BAC", "retail_pct"] == 0.30
    assert df.loc["BAC", "float_turnover"] == 0.05


def test_fetch_yf_failure_yields_nan_row(monkeypatch):
    import yfinance

    class Boom:
        def __init__(self, t):
            raise RuntimeError("api down")

    monkeypatch.setattr(yfinance, "Ticker", Boom)
    row = pos.fetch_yf_positioning("XXX")
    assert row["ticker"] == "XXX" and row["si_source"] == "none"
    assert np.isnan(row["float_shares"])
