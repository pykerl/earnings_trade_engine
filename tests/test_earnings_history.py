import json
from datetime import date

import pandas as pd

from common import config
from ingest import earnings_history as eh


def test_rate_limiter_enforces_daily_ration_and_gap(tmp_path):
    now = {"t": 1_000_000.0}
    sleeps = []
    lim = eh.AVRateLimiter(
        state_path=tmp_path / "state.json",
        clock=lambda: now["t"],
        sleeper=lambda s: (sleeps.append(s), now.__setitem__("t", now["t"] + s)),
    )
    assert lim.calls_remaining() == config.AV_MAX_CALLS_PER_DAY
    for _ in range(config.AV_MAX_CALLS_PER_DAY):
        assert lim.acquire()
        now["t"] += 1.0  # only 1s passes between attempts -> limiter must sleep
    assert not lim.acquire(), "26th call of the day must be refused"
    assert all(s >= config.AV_MIN_SECONDS_BETWEEN_CALLS - 1.01 for s in sleeps)
    assert len(sleeps) == config.AV_MAX_CALLS_PER_DAY - 1

    # state survives a restart
    lim2 = eh.AVRateLimiter(state_path=tmp_path / "state.json", clock=lambda: now["t"])
    assert lim2.calls_remaining() == 0
    # ration resets on a new day
    now["t"] += 86_400
    assert lim2.calls_remaining() == config.AV_MAX_CALLS_PER_DAY


def test_backfill_queue_prioritizes_near_reporters(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "AV_QUEUE_JSON", tmp_path / "q.json")
    today = date(2026, 7, 11)
    events = pd.DataFrame(
        {
            "ticker": ["FAR", "NEAR", "DEEP"],
            "earnings_date": [date(2026, 7, 30), date(2026, 7, 14), date(2026, 7, 13)],
        }
    )
    history = pd.DataFrame(
        {
            "ticker": ["DEEP"] * config.MIN_HISTORY_QUARTERS,
            "event_date": [date(2020 + i, 1, 1) for i in range(config.MIN_HISTORY_QUARTERS)],
            "session": "unknown",
            "eps_estimate": float("nan"),
            "reported_eps": float("nan"),
            "surprise_pct": float("nan"),
            "source": "yfinance",
        }
    )
    queue = eh.build_backfill_queue(events, history, today=today)
    assert [q["ticker"] for q in queue] == ["NEAR", "FAR"], "deep history excluded, near reporter first"
    assert queue[0]["priority"] == 0 and queue[1]["priority"] == 1
    assert json.loads((tmp_path / "q.json").read_text())[0]["ticker"] == "NEAR"


def test_parse_av_earnings_sessions_and_numbers():
    payload = {
        "quarterlyEarnings": [
            {"reportedDate": "2026-04-14", "reportTime": "pre-market",
             "estimatedEPS": "4.61", "reportedEPS": "5.07", "surprisePercentage": "9.9"},
            {"reportedDate": "2026-01-14", "reportTime": "post-market",
             "estimatedEPS": "None", "reportedEPS": "4.81", "surprisePercentage": "None"},
            {"reportedDate": ""},  # malformed row ignored
        ]
    }
    df = eh.parse_av_earnings(payload, "JPM")
    assert len(df) == 2
    assert list(df["session"]) == ["BMO", "AMC"]
    assert df.loc[0, "eps_estimate"] == 4.61
    assert pd.isna(df.loc[1, "eps_estimate"])


def test_dedupe_prefers_known_session():
    df = pd.DataFrame(
        [
            {"ticker": "A", "event_date": date(2026, 1, 5), "session": "unknown",
             "eps_estimate": 1.0, "reported_eps": 1.1, "surprise_pct": 10.0, "source": "yfinance"},
            {"ticker": "A", "event_date": date(2026, 1, 5), "session": "AMC",
             "eps_estimate": 1.0, "reported_eps": 1.1, "surprise_pct": 10.0, "source": "alphavantage"},
        ]
    )
    out = eh.dedupe_history(df)
    assert len(out) == 1 and out.loc[0, "session"] == "AMC"


def test_av_backfill_noop_without_key(monkeypatch, tmp_path):
    monkeypatch.delenv(config.AV_API_KEY_ENV, raising=False)
    monkeypatch.setattr(config, "AV_QUEUE_JSON", tmp_path / "q.json")
    (tmp_path / "q.json").write_text('[{"ticker": "JPM", "purpose": "earnings_dates"}]')
    out = eh.run_av_backfill()
    assert out.empty
    assert json.loads((tmp_path / "q.json").read_text()), "queue must be preserved"


class _FakeResp:
    status_code = 200
    def __init__(self, payload):
        self._payload = payload
    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payloads):
        self.payloads = payloads
        self.calls = []
    def get(self, url, params=None, timeout=None):
        self.calls.append(params["symbol"])
        return _FakeResp(self.payloads[params["symbol"]])


def test_av_backfill_drains_queue_within_budget(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AV_QUEUE_JSON", tmp_path / "q.json")
    (tmp_path / "q.json").write_text(json.dumps(
        [{"ticker": t, "purpose": "earnings_dates"} for t in ["JPM", "WFC", "C"]]
    ))
    now = {"t": 1_000_000.0}
    lim = eh.AVRateLimiter(state_path=tmp_path / "s.json", clock=lambda: now["t"],
                           sleeper=lambda s: now.__setitem__("t", now["t"] + s))
    fake = _FakeSession({
        "JPM": {"quarterlyEarnings": [{"reportedDate": "2026-04-14", "reportTime": "pre-market"}]},
        "WFC": {"quarterlyEarnings": [{"reportedDate": "2026-04-15", "reportTime": "pre-market"}]},
    })
    out = eh.run_av_backfill(max_calls=2, limiter=lim, session=fake, api_key="test-key")
    assert fake.calls == ["JPM", "WFC"], "budget of 2 stops before C"
    assert set(out["ticker"]) == {"JPM", "WFC"}
    left = json.loads((tmp_path / "q.json").read_text())
    assert [q["ticker"] for q in left] == ["C"], "unfetched names stay queued"


def test_av_backfill_requeues_on_throttle_notice(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "AV_QUEUE_JSON", tmp_path / "q.json")
    (tmp_path / "q.json").write_text(json.dumps([{"ticker": "JPM", "purpose": "earnings_dates"}]))
    now = {"t": 1_000_000.0}
    lim = eh.AVRateLimiter(state_path=tmp_path / "s.json", clock=lambda: now["t"],
                           sleeper=lambda s: now.__setitem__("t", now["t"] + s))
    fake = _FakeSession({"JPM": {"Note": "API call frequency exceeded"}})
    out = eh.run_av_backfill(limiter=lim, session=fake, api_key="test-key")
    assert out.empty
    assert json.loads((tmp_path / "q.json").read_text())[0]["ticker"] == "JPM"
