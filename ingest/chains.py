"""Option chains -> implied earnings move (plan §3 block 3).

For every name reporting within the next 10 trading days:
  * pick the expiry immediately after the event (BMO -> event day is fine;
    AMC/unknown -> expiry must be on/after the NEXT trading day, otherwise
    the option dies before the move happens),
  * implied move = ATM straddle mid / spot, also recorded at the ask (buyer's
    realistic entry) and at the bid (seller's), plus spread % and OI/volume,
  * a strike ladder (±20% of spot) so scoring can size iron-fly wings and
    strangle legs without re-hitting the API.

Quotes are 15-min delayed yfinance — fine for an EOD process (plan §2).
Names with dead/stale quotes (zero bid or ask at the ATM) are recorded with
`quote_ok = False` and get screened downstream.

Outputs: data/chains.parquet (one row per event), plus a `ladders` parquet
next to it (per-strike quotes).
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.chains")

LADDER_PARQUET = config.DATA_DIR / "ladders.parquet"
LADDER_WINDOW = 0.20  # strikes within ±20% of spot

CHAIN_COLUMNS = [
    "ticker", "earnings_date", "session", "spot", "expiry", "atm_strike",
    "straddle_bid", "straddle_mid", "straddle_ask",
    "implied_move_bid", "implied_move_mid", "implied_move_ask",
    "spread_pct", "open_interest", "volume", "quote_ok",
]
LADDER_COLUMNS = [
    "ticker", "expiry", "strike",
    "call_bid", "call_ask", "put_bid", "put_ask", "call_oi", "put_oi",
]


def reaction_day(event_date: date, session: str) -> date:
    """First day whose close reflects the earnings reaction."""
    if session == "BMO":
        d = event_date
    else:  # AMC or unknown: be safe, the move may land the next trading day
        d = event_date + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def pick_expiry(expiries: list[str], reaction: date) -> str | None:
    """First listed expiry on/after the reaction day."""
    usable = sorted(e for e in expiries if date.fromisoformat(e) >= reaction)
    return usable[0] if usable else None


def _mid(bid: float, ask: float) -> float:
    return (bid + ask) / 2.0


def build_ladder(calls: pd.DataFrame, puts: pd.DataFrame, spot: float) -> pd.DataFrame:
    """Per-strike two-sided quotes near the money."""
    lo, hi = spot * (1 - LADDER_WINDOW), spot * (1 + LADDER_WINDOW)
    c = calls[(calls["strike"] >= lo) & (calls["strike"] <= hi)][
        ["strike", "bid", "ask", "openInterest"]
    ].rename(columns={"bid": "call_bid", "ask": "call_ask", "openInterest": "call_oi"})
    p = puts[(puts["strike"] >= lo) & (puts["strike"] <= hi)][
        ["strike", "bid", "ask", "openInterest"]
    ].rename(columns={"bid": "put_bid", "ask": "put_ask", "openInterest": "put_oi"})
    ladder = c.merge(p, on="strike", how="outer").sort_values("strike").reset_index(drop=True)
    for col in ("call_bid", "call_ask", "put_bid", "put_ask"):
        ladder[col] = pd.to_numeric(ladder[col], errors="coerce").fillna(0.0)
    for col in ("call_oi", "put_oi"):
        ladder[col] = pd.to_numeric(ladder[col], errors="coerce").fillna(0).astype(int)
    return ladder


def summarize_event(ladder: pd.DataFrame, spot: float) -> dict | None:
    """ATM straddle stats from a ladder; None when there is no usable strike."""
    two_sided = ladder[(ladder["call_ask"] > 0) & (ladder["put_ask"] > 0)]
    if two_sided.empty or spot <= 0:
        return None
    atm = two_sided.iloc[(two_sided["strike"] - spot).abs().argsort().iloc[0]]
    bid = float(atm["call_bid"] + atm["put_bid"])
    ask = float(atm["call_ask"] + atm["put_ask"])
    mid = _mid(bid, ask)
    quote_ok = bid > 0 and ask > 0 and mid > 0
    return {
        "atm_strike": float(atm["strike"]),
        "straddle_bid": bid,
        "straddle_mid": mid,
        "straddle_ask": ask,
        "implied_move_bid": bid / spot,
        "implied_move_mid": mid / spot,
        "implied_move_ask": ask / spot,
        "spread_pct": (ask - bid) / mid if mid > 0 else np.inf,
        "open_interest": int(atm["call_oi"] + atm["put_oi"]),
        "quote_ok": quote_ok,
    }


def fetch_event_chain(ticker: str, event_date: date, session: str) -> tuple[dict, pd.DataFrame] | None:
    """One name's event summary + ladder; None on failure (logged, skipped)."""
    import yfinance as yf

    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()

    for attempt in range(2):
        try:
            tk = yf.Ticker(ticker)
            spot = float(tk.fast_info["lastPrice"])
            expiry = pick_expiry(list(tk.options or ()), reaction_day(event_date, session))
            if expiry is None:
                log.warning("%s: no expiry on/after the event; skipping", ticker)
                return None
            oc = tk.option_chain(expiry)
            ladder = build_ladder(oc.calls, oc.puts, spot)
            summary = summarize_event(ladder, spot)
            if summary is None:
                log.warning("%s: no two-sided ATM quotes for %s; skipping", ticker, expiry)
                return None
            volume = int(
                pd.to_numeric(oc.calls["volume"], errors="coerce").fillna(0).sum()
                + pd.to_numeric(oc.puts["volume"], errors="coerce").fillna(0).sum()
            )
            row = {
                "ticker": ticker, "earnings_date": event_date, "session": session,
                "spot": spot, "expiry": expiry, "volume": volume, **summary,
            }
            ladder = ladder.assign(ticker=ticker, expiry=expiry)[LADDER_COLUMNS]
            return row, ladder
        except Exception as exc:
            log.warning("chain fetch failed for %s (attempt %d/2): %s", ticker, attempt + 1, exc)
            time.sleep(2)
    return None


def trading_day_cutoff(today: date, n: int = config.CHAIN_TRADING_DAYS_AHEAD) -> date:
    days = pd.bdate_range(today, periods=n + 1)
    return days[-1].date()


def run(events: pd.DataFrame | None = None, today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    today = today or date.today()
    if events is None:
        events = pd.read_parquet(config.EVENTS_PARQUET)
    cutoff = trading_day_cutoff(today)
    soon = events[(events["earnings_date"] >= today) & (events["earnings_date"] <= cutoff)]
    log.info("pulling chains for %d names reporting %s..%s", len(soon), today, cutoff)

    rows, ladders = [], []
    for ev in soon.itertuples(index=False):
        res = fetch_event_chain(ev.ticker, ev.earnings_date, ev.session)
        if res is None:
            continue
        row, ladder = res
        rows.append(row)
        ladders.append(ladder)

    chains = pd.DataFrame(rows, columns=CHAIN_COLUMNS)
    ladder_df = (
        pd.concat(ladders, ignore_index=True) if ladders else pd.DataFrame(columns=LADDER_COLUMNS)
    )
    chains.to_parquet(config.CHAINS_PARQUET, index=False)
    ladder_df.to_parquet(LADDER_PARQUET, index=False)
    log.info("chains: %d events with usable ATM quotes -> %s", len(chains), config.CHAINS_PARQUET)
    return chains


if __name__ == "__main__":
    config.setup_logging()
    run()
