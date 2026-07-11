"""Realized earnings-day moves with BMO/AMC alignment (plan §3 block 2).

For each (ticker, past earnings date):
  * BMO  — the report hits before that day's open, so the reaction is that
           day's open gap + day move: close(D-1) -> close(D).
  * AMC  — the report hits after the close, so the reaction is the NEXT
           trading day: close(D) -> close(D+1).
  * unknown — take max(|day|, |next-day|) and flag lower confidence.

Moves use adjusted closes so splits/dividends don't masquerade as earnings
moves. Events without full price coverage (listing gaps, >15yr old) are
skipped and logged.

Output: data/moves.parquet
  ticker, event_date, session, move (signed), abs_move, confidence (high/low)
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.moves")

MOVE_COLUMNS = ["ticker", "event_date", "session", "move", "abs_move", "confidence"]


def _event_move(dates: np.ndarray, closes: np.ndarray, event_date: date, session: str):
    """Return (signed move, confidence) or None when price coverage is missing.

    `dates` must be a sorted array of numpy datetime64[D] trading days.
    """
    d = np.datetime64(event_date, "D")

    def day_move(reaction_idx: int) -> float | None:
        if reaction_idx - 1 < 0 or reaction_idx >= len(closes):
            return None
        return float(closes[reaction_idx] / closes[reaction_idx - 1] - 1.0)

    # first trading day >= D (the reaction day for a BMO report, and D itself
    # when D is a trading day)
    on_or_after = int(np.searchsorted(dates, d, side="left"))
    # last trading day <= D (the pricing base for an AMC report)
    on_or_before = int(np.searchsorted(dates, d, side="right")) - 1

    if session == "BMO":
        mv = day_move(on_or_after)
        return (mv, "high") if mv is not None else None
    if session == "AMC":
        mv = day_move(on_or_before + 1)
        return (mv, "high") if mv is not None else None

    # unknown timestamp: the reaction is either day D or D+1 — take the larger
    same_day = day_move(on_or_after)
    next_day = day_move(on_or_before + 1)
    candidates = [m for m in (same_day, next_day) if m is not None]
    if not candidates:
        return None
    return (max(candidates, key=abs), "low")


def compute_moves(history: pd.DataFrame, prices: pd.DataFrame) -> pd.DataFrame:
    """history: earnings_history schema; prices: long OHLCV with adj_close."""
    out = []
    prices = prices.sort_values(["ticker", "date"])
    skipped = 0
    for ticker, hist in history.groupby("ticker"):
        px = prices[prices["ticker"] == ticker]
        if len(px) < 3:  # need at least prior close, event day, next day
            log.warning("no usable price history for %s; skipping %d events", ticker, len(hist))
            continue
        dates = px["date"].to_numpy(dtype="datetime64[D]")
        closes = px["adj_close"].to_numpy(dtype=float)
        for row in hist.itertuples(index=False):
            res = _event_move(dates, closes, row.event_date, row.session)
            if res is None:
                skipped += 1
                continue
            mv, confidence = res
            out.append(
                {
                    "ticker": ticker,
                    "event_date": row.event_date,
                    "session": row.session,
                    "move": mv,
                    "abs_move": abs(mv),
                    "confidence": confidence,
                }
            )
    if skipped:
        log.info("skipped %d events without price coverage", skipped)
    return pd.DataFrame(out, columns=MOVE_COLUMNS)


def run(history: pd.DataFrame | None = None, prices: pd.DataFrame | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if history is None:
        history = pd.read_parquet(config.EARNINGS_HISTORY_PARQUET)
    if prices is None:
        prices = pd.read_parquet(config.PRICES_PARQUET)
    moves = compute_moves(history, prices)
    moves.to_parquet(config.MOVES_PARQUET, index=False)
    log.info(
        "moves: %d events across %d names (median |move| %.2f%%) -> %s",
        len(moves), moves["ticker"].nunique() if len(moves) else 0,
        100 * moves["abs_move"].median() if len(moves) else float("nan"),
        config.MOVES_PARQUET,
    )
    return moves


if __name__ == "__main__":
    config.setup_logging()
    run()
