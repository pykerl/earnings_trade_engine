"""Synthetic fixture data for offline end-to-end runs (`run.py daily --fixtures`).

Generates a fake-but-plausible universe, 6 years of daily prices with real
earnings-day jumps injected, an upcoming-week calendar, matching earnings
history, and option chains/ladders (built through the SAME build_ladder /
summarize_event code paths as production).

Everything lands in the normal data/ artifact locations so the downstream
pipeline (moves -> fair -> rank -> dashboard -> pre-registration) runs
unchanged. Outputs are watermarked SYNTHETIC by run.py and pre-registration
rows are diverted to data/demo/ — never the real log.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import config
from ingest.chains import LADDER_COLUMNS, LADDER_PARQUET, build_ladder, reaction_day, summarize_event
from ingest.earnings_history import HISTORY_COLUMNS

log = logging.getLogger("ete.fixtures")

SECTORS = ["Financials", "Information Technology", "Health Care", "Energy"]
N_NAMES = 40
N_REPORTERS = 18
YEARS = 6


def _quarterly_dates(rng, end: date, n: int) -> list[date]:
    dates = []
    d = end
    for _ in range(n):
        d = d - timedelta(days=int(rng.integers(88, 95)))
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        dates.append(d)
    return sorted(dates)


def generate_all(today: date, seed: int = 20260711) -> None:
    rng = np.random.default_rng(seed)
    config.ensure_dirs()

    # ---- universe -----------------------------------------------------------
    tickers = [f"SYN{i:02d}" for i in range(N_NAMES)]
    universe = pd.DataFrame(
        {
            "ticker": tickers,
            "name": [f"Synthetic Corp {i:02d}" for i in range(N_NAMES)],
            "sector": [SECTORS[i % len(SECTORS)] for i in range(N_NAMES)],
            "sub_industry": "Synthetic",
        }
    )
    universe.to_parquet(config.UNIVERSE_PARQUET, index=False)

    # ---- per-name personalities --------------------------------------------
    base_vol = rng.uniform(0.012, 0.028, N_NAMES)            # daily vol
    event_scale = rng.uniform(0.02, 0.09, N_NAMES)           # typical |earnings move|
    cap_b = np.round(np.exp(rng.uniform(np.log(5), np.log(600), N_NAMES)), 1)

    # ---- prices with injected earnings jumps + history ----------------------
    days = pd.bdate_range(end=today - timedelta(days=1), periods=int(252 * YEARS))
    price_frames, history_rows = [], []
    sessions = ["BMO", "AMC", "AMC", "BMO", "unknown"]
    for i, t in enumerate(tickers):
        past_events = _quarterly_dates(rng, today - timedelta(days=20), 4 * YEARS - 2)
        session_cycle = [sessions[(i + j) % len(sessions)] for j in range(len(past_events))]
        rets = rng.normal(0.0004, base_vol[i], len(days))
        day_index = {d.date(): k for k, d in enumerate(days)}
        for ev, sess in zip(past_events, session_cycle):
            jump = rng.standard_t(df=4) * event_scale[i] * 0.8
            k = day_index.get(ev)
            if k is None:
                continue
            # place the jump on the correct reaction day for the session
            if sess == "BMO":
                rets[k] += jump
            else:  # AMC and unknown: reaction lands the next trading day
                if k + 1 < len(rets):
                    rets[k + 1] += jump
            history_rows.append(
                {
                    "ticker": t, "event_date": ev, "session": sess,
                    "eps_estimate": round(float(rng.uniform(0.5, 3.0)), 2),
                    "reported_eps": round(float(rng.uniform(0.5, 3.0)), 2),
                    "surprise_pct": round(float(rng.normal(0, 8)), 1),
                    "source": "yfinance",
                }
            )
        closes = 20 * np.exp(np.cumsum(rets)) * (1 + i * 0.15)
        price_frames.append(
            pd.DataFrame(
                {
                    "ticker": t, "date": days,
                    "open": closes, "high": closes * 1.01, "low": closes * 0.99,
                    "close": closes, "adj_close": closes,
                    "volume": rng.integers(1e5, 5e6, len(days)),
                }
            )
        )
    pd.concat(price_frames, ignore_index=True).to_parquet(config.PRICES_PARQUET, index=False)
    history = pd.DataFrame(history_rows, columns=HISTORY_COLUMNS)
    # thin out a few names so the AV-queue / shrinkage paths get exercised
    thin = set(tickers[::9])
    history = history[
        ~history["ticker"].isin(thin)
        | (history["event_date"] > today - timedelta(days=400))
    ]
    history.to_parquet(config.EARNINGS_HISTORY_PARQUET, index=False)

    # ---- upcoming week calendar ---------------------------------------------
    reporters = tickers[:N_REPORTERS]
    week_days = [d.date() for d in pd.bdate_range(today + timedelta(days=1), periods=5)]
    events = pd.DataFrame(
        {
            "ticker": reporters,
            "earnings_date": [week_days[i % len(week_days)] for i in range(N_REPORTERS)],
            "session": [sessions[i % len(sessions)] for i in range(N_REPORTERS)],
            "source_agreement": ["confirmed" if i % 4 else "single_source" for i in range(N_REPORTERS)],
            "sources": "yfinance,nasdaq",
        }
    ).merge(universe[["ticker", "name", "sector"]], on="ticker")
    events["cap_b"] = [cap_b[tickers.index(t)] for t in events["ticker"]]
    events.to_parquet(config.EVENTS_PARQUET, index=False)

    # ---- chains + ladders through the production summarizer -----------------
    prices = pd.concat(price_frames, ignore_index=True)
    chain_rows, ladder_frames = [], []
    for j, ev in enumerate(events.itertuples(index=False)):
        i = tickers.index(ev.ticker)
        spot = float(prices[prices["ticker"] == ev.ticker]["close"].iloc[-1])
        fair_ish = event_scale[i]
        richness = [0.55, 0.8, 1.0, 1.25, 1.7][j % 5]      # cheap ... very rich
        implied = fair_ish * richness
        spread_pct = [0.02, 0.04, 0.06, 0.09, 0.13][j % 5]  # some get screened
        oi = int([3000, 1500, 800, 900, 120][(j + 1) % 5])  # some fail the OI screen

        step = max(round(spot * 0.025, 0), 0.5)
        strikes = np.array([spot + k * step for k in range(-8, 9)])
        atm_tv = implied * spot / 2
        tv = atm_tv * np.exp(-np.abs(strikes - spot) / (spot * max(implied, 0.02)))
        call_fair = np.maximum(spot - strikes, 0) + tv
        put_fair = np.maximum(strikes - spot, 0) + tv
        half = np.maximum(spread_pct * (call_fair + put_fair) / 4, 0.03)

        expiry = (reaction_day(ev.earnings_date, ev.session) + timedelta(days=1)).isoformat()
        calls = pd.DataFrame(
            {"strike": strikes, "bid": call_fair - half, "ask": call_fair + half,
             "openInterest": oi // 2, "volume": oi // 4}
        )
        puts = pd.DataFrame(
            {"strike": strikes, "bid": put_fair - half, "ask": put_fair + half,
             "openInterest": oi - oi // 2, "volume": oi // 4}
        )
        ladder = build_ladder(calls, puts, spot)
        summary = summarize_event(ladder, spot)
        if summary is None:
            continue
        chain_rows.append(
            {"ticker": ev.ticker, "earnings_date": ev.earnings_date, "session": ev.session,
             "spot": spot, "expiry": expiry, "volume": int(oi), **summary}
        )
        ladder_frames.append(ladder.assign(ticker=ev.ticker, expiry=expiry)[LADDER_COLUMNS])

    pd.DataFrame(chain_rows).to_parquet(config.CHAINS_PARQUET, index=False)
    pd.concat(ladder_frames, ignore_index=True).to_parquet(LADDER_PARQUET, index=False)

    # ---- positioning: a few crowded shorts so the squeeze tab exercises ------
    floats = rng.uniform(50e6, 5e9, N_NAMES)
    si_pct = rng.uniform(0.005, 0.04, N_NAMES)
    si_pct[::6] = rng.uniform(0.09, 0.28, len(si_pct[::6]))  # crowded shorts
    inst = rng.uniform(0.35, 0.92, N_NAMES)
    insider = rng.uniform(0.0, 0.12, N_NAMES)
    avg_vol = floats * rng.uniform(0.004, 0.05, N_NAMES)
    positioning = pd.DataFrame(
        {
            "ticker": tickers,
            "float_shares": floats,
            "shares_outstanding": floats * 1.05,
            "inst_pct": inst,
            "insider_pct": insider,
            "retail_pct": (1 - inst - insider).clip(0, 1),
            "si_shares": floats * si_pct,
            "si_pct_float": si_pct,
            "days_to_cover": (floats * si_pct) / avg_vol,
            "avg_vol_10d": avg_vol,
            "float_turnover": avg_vol / floats,
            "si_trend": rng.normal(0.0, 0.15, N_NAMES),
            "si_source": ["nasdaq" if i % 2 else "yahoo" for i in range(N_NAMES)],
        }
    )
    positioning.to_parquet(config.POSITIONING_PARQUET, index=False)
    log.info(
        "fixtures: %d names, %d price rows, %d history events, %d upcoming, %d chains",
        N_NAMES, len(prices), len(history), len(events), len(chain_rows),
    )
