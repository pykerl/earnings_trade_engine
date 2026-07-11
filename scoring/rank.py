"""Edge score, liquidity screen, strategy mapping (plan §3 blocks 3-4).

edge  = (implied_mid - fair) / fair
z     = (implied_mid - fair) / se_fair        (se recovered from the model CI)
score = z x liquidity multiplier x confidence multiplier   (v1: no ML)

Liquidity screen (plan block 3): DROP names with ATM straddle spread >
MAX_SPREAD_PCT (10%) of straddle value, OI < 500 on the event expiry, or
dead quotes. Screened names stay in the output flagged `screened` so the
dashboard can show the kill list — expect it to eat a third of the list.

Strategy mapping (defined-risk only, $10k paper account, plan block 4):
  * edge >= +15% and z >= 1  -> iron fly: sell ATM straddle at BID, buy wings
    at ASK; wings chosen from the real ladder maximizing credit subject to
    max loss <= $250.
  * edge <= -15% and z <= -1 -> long straddle at ASK if debit <= $250, else
    the nearest strangle whose combined ask fits <= $250.
  * otherwise -> no trade (the default state).
Entries always priced at the realistic side (buy at ask / sell at bid).

Output: data/scored.parquet, ranked by |score| among unscreened names.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import config
from ingest.chains import LADDER_PARQUET

log = logging.getLogger("ete.rank")

Z80 = 1.2816

SESSION_UNKNOWN_MULT = 0.85
SINGLE_SOURCE_MULT = 0.90
LOW_CONF_PENALTY = 0.30


# ------------------------------------------------------------- multipliers --
def liquidity_multiplier(spread_pct: float) -> float:
    """1.0 up to the soft spread threshold, linear to 0 at the hard cap."""
    if spread_pct <= config.SOFT_SPREAD_PCT:
        return 1.0
    if spread_pct >= config.MAX_SPREAD_PCT:
        return 0.0
    return (config.MAX_SPREAD_PCT - spread_pct) / (config.MAX_SPREAD_PCT - config.SOFT_SPREAD_PCT)


def confidence_multiplier(w_name: float, low_conf_share: float, session: str, agreement: str) -> float:
    mult = 0.5 + 0.5 * float(w_name)          # sample-size term (w = n/(n+k))
    mult *= 1.0 - LOW_CONF_PENALTY * float(low_conf_share)
    if session == "unknown":
        mult *= SESSION_UNKNOWN_MULT
    if agreement == "single_source":
        mult *= SINGLE_SOURCE_MULT
    return mult


# ------------------------------------------------------------ trade timing --
def entry_deadline(event_date: date, session: str) -> date:
    """Last trading day on which the position can be opened before the move.

    BMO reports hit before that day's open, so entry must happen the prior
    trading day. AMC positions can be opened the event day itself (before the
    close). Unknown timestamps are treated like BMO to be safe.
    """
    d = event_date if session == "AMC" else event_date - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def next_trading_session(today: date) -> date:
    d = today
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


# ---------------------------------------------------------- structure legs --
def _wing_candidates(ladder: pd.DataFrame, atm: float) -> list[tuple[pd.Series, pd.Series]]:
    """k-th strike above paired with k-th below the ATM, two-sided quotes only."""
    above = ladder[(ladder["strike"] > atm) & (ladder["call_ask"] > 0)].sort_values("strike")
    below = ladder[(ladder["strike"] < atm) & (ladder["put_ask"] > 0)].sort_values(
        "strike", ascending=False
    )
    return [(above.iloc[k], below.iloc[k]) for k in range(min(len(above), len(below)))]


def map_iron_fly(row: pd.Series, ladder: pd.DataFrame) -> dict | None:
    """Widest-credit iron fly with max loss <= $250; None if nothing fits."""
    best = None
    for call_wing, put_wing in _wing_candidates(ladder, row["atm_strike"]):
        credit = row["straddle_bid"] - float(call_wing["call_ask"]) - float(put_wing["put_ask"])
        if credit <= 0:
            continue
        width = max(
            float(call_wing["strike"]) - row["atm_strike"],
            row["atm_strike"] - float(put_wing["strike"]),
        )
        max_loss = (width - credit) * 100.0
        if max_loss > config.MAX_LOSS_DOLLARS or max_loss <= 0:
            continue
        if best is None or credit > best["credit"]:
            best = {
                "structure": "iron fly",
                "detail": (
                    f"short {row['atm_strike']:g} straddle @ bid, "
                    f"long {put_wing['strike']:g}P / {call_wing['strike']:g}C @ ask"
                ),
                "entry_side": "credit",
                "entry_price": credit * 100.0,
                "credit": credit,
                "max_gain": credit * 100.0,
                "max_loss": max_loss,
                "legs_json": json.dumps([
                    {"action": "SELL", "right": "CALL", "strike": row["atm_strike"]},
                    {"action": "SELL", "right": "PUT", "strike": row["atm_strike"]},
                    {"action": "BUY", "right": "CALL", "strike": float(call_wing["strike"])},
                    {"action": "BUY", "right": "PUT", "strike": float(put_wing["strike"])},
                ]),
            }
    return best


def map_long_vol(row: pd.Series, ladder: pd.DataFrame) -> dict | None:
    """Long straddle at the ask if it fits $250, else nearest affordable strangle."""
    debit = row["straddle_ask"] * 100.0
    if debit <= config.MAX_LOSS_DOLLARS:
        return {
            "structure": "long straddle",
            "detail": f"long {row['atm_strike']:g} straddle @ ask",
            "entry_side": "debit",
            "entry_price": debit,
            "max_gain": np.inf,
            "max_loss": debit,
            "legs_json": json.dumps([
                {"action": "BUY", "right": "CALL", "strike": row["atm_strike"]},
                {"action": "BUY", "right": "PUT", "strike": row["atm_strike"]},
            ]),
        }
    for call_leg, put_leg in _wing_candidates(ladder, row["atm_strike"]):
        debit = (float(call_leg["call_ask"]) + float(put_leg["put_ask"])) * 100.0
        if 0 < debit <= config.MAX_LOSS_DOLLARS:
            return {
                "structure": "long strangle",
                "detail": f"long {put_leg['strike']:g}P / {call_leg['strike']:g}C @ ask",
                "entry_side": "debit",
                "entry_price": debit,
                "max_gain": np.inf,
                "max_loss": debit,
                "legs_json": json.dumps([
                    {"action": "BUY", "right": "CALL", "strike": float(call_leg["strike"])},
                    {"action": "BUY", "right": "PUT", "strike": float(put_leg["strike"])},
                ]),
            }
    return None


def map_structure(row: pd.Series, ladder: pd.DataFrame) -> dict:
    no_trade = {
        "structure": "no trade", "detail": "", "entry_side": "",
        "entry_price": np.nan, "max_gain": np.nan, "max_loss": np.nan,
        "legs_json": "",
    }
    if row.get("screened", False):
        return {**no_trade, "structure": "screened out"}
    if abs(row["edge"]) < config.EDGE_NO_TRADE_BAND or abs(row["z"]) < config.MIN_ABS_Z:
        return no_trade
    mapped = (
        map_iron_fly(row, ladder) if row["edge"] > 0 else map_long_vol(row, ladder)
    )
    if mapped is None:
        return {**no_trade, "structure": "no affordable structure"}
    mapped.pop("credit", None)
    return mapped


# -------------------------------------------------------------------- score --
def score_events(
    chains: pd.DataFrame, fair: pd.DataFrame, events: pd.DataFrame, ladders: pd.DataFrame
) -> pd.DataFrame:
    df = chains.merge(fair, on="ticker", how="inner").merge(
        events[["ticker", "source_agreement", "name", "sector"]], on="ticker", how="left"
    )
    if df.empty:
        log.warning("nothing to score (no chains matched fair estimates)")
        return df

    df["edge"] = (df["implied_move_mid"] - df["fair_move"]) / df["fair_move"]
    se = ((df["ci_high"] - df["ci_low"]) / (2 * Z80)).clip(lower=1e-6)
    df["z"] = (df["implied_move_mid"] - df["fair_move"]) / se

    df["screen_reason"] = ""
    df.loc[~df["quote_ok"], "screen_reason"] = "dead quotes"
    df.loc[df["open_interest"] < config.MIN_OPEN_INTEREST, "screen_reason"] = (
        f"OI < {config.MIN_OPEN_INTEREST}"
    )
    df.loc[df["spread_pct"] > config.MAX_SPREAD_PCT, "screen_reason"] = (
        f"spread > {config.MAX_SPREAD_PCT:.0%}"
    )
    df["screened"] = df["screen_reason"] != ""

    df["liq_mult"] = df["spread_pct"].map(liquidity_multiplier)
    df["conf_mult"] = [
        confidence_multiplier(r.w_name, r.low_conf_share, r.session, r.source_agreement)
        for r in df.itertuples(index=False)
    ]
    df["score"] = df["z"] * df["liq_mult"] * df["conf_mult"]
    df.loc[df["screened"], "score"] = 0.0

    # spread drag vs gross edge (plan §4 cost reality check)
    edge_dollars = (df["implied_move_mid"] - df["fair_move"]).abs() * df["spot"] * 100.0
    spread_dollars = (df["straddle_ask"] - df["straddle_bid"]) * 100.0
    df["spread_cost_pct_of_edge"] = np.where(
        edge_dollars > 0, 100.0 * spread_dollars / edge_dollars, np.inf
    )

    df["entry_by"] = [
        entry_deadline(r.earnings_date, r.session) for r in df.itertuples(index=False)
    ]

    structures = []
    for _, row in df.iterrows():
        lad = ladders[(ladders["ticker"] == row["ticker"]) & (ladders["expiry"] == row["expiry"])]
        structures.append(map_structure(row, lad))
    df = pd.concat([df.reset_index(drop=True), pd.DataFrame(structures)], axis=1)

    df["flags"] = [
        "; ".join(
            f for f, on in [
                (r.screen_reason, bool(r.screened)),
                ("session unknown", r.session == "unknown"),
                ("single-source date", r.source_agreement == "single_source"),
                (f"thin history (n={r.n_events})", r.n_events < config.MIN_HISTORY_QUARTERS),
                ("low-conf moves", r.low_conf_share > 0.25),
                ("wide market", config.SOFT_SPREAD_PCT < r.spread_pct <= config.MAX_SPREAD_PCT),
            ] if on
        )
        for r in df.itertuples(index=False)
    ]

    df = df.sort_values(["screened", "score"], key=lambda s: s.abs() if s.name == "score" else s,
                        ascending=[True, False]).reset_index(drop=True)
    return df


def run(today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    chains = pd.read_parquet(config.CHAINS_PARQUET)
    fair = pd.read_parquet(config.FAIR_PARQUET)
    events = pd.read_parquet(config.EVENTS_PARQUET)
    ladders = pd.read_parquet(LADDER_PARQUET)
    scored = score_events(chains, fair, events, ladders)
    scored.to_parquet(config.SCORED_PARQUET, index=False)
    n_live = int((~scored["screened"]).sum()) if len(scored) else 0
    log.info("scored %d events (%d pass liquidity screen) -> %s",
             len(scored), n_live, config.SCORED_PARQUET)
    return scored


if __name__ == "__main__":
    config.setup_logging()
    run()
