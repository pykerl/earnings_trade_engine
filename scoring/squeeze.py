"""Squeeze watch: crowded shorts into earnings (tab 2).

Composite squeeze score per upcoming reporter — percentile ranks within the
reporter cohort, weighted:

    short % of float   0.35   (the crowd that must buy to exit)
    days-to-cover      0.25   (how long the exit takes at normal volume)
    float turnover     0.20   (small float + big volume = moves fast)
    small float        0.10   (rank of 1/float)
    SI trend           0.10   (shorts still piling in vs already covering)

Candidates: si_pct_float >= SQUEEZE_MIN_SI (5%) and score >= SQUEEZE_SCORE_MIN.
Trade mapping (defined-risk, long side only): the listed call nearest one
implied move above spot on the event expiry, at the ASK, cost <= $250 —
squeeze plays are lottery tickets, sized accordingly (1 contract, never
part of the tab-1 risk budget).

The same data feeds tab 1's safety rail: names with si_pct_float >=
SQUEEZE_RISK_SI (8%) are flagged and excluded from short-premium sizing —
squeeze candidates are how iron-fly sellers get carried out.

Output: data/squeeze.parquet
"""

from __future__ import annotations

import json
import logging
from datetime import date

import numpy as np
import pandas as pd

from common import config
from ingest.chains import LADDER_PARQUET
from scoring.rank import entry_deadline

log = logging.getLogger("ete.squeeze")

WEIGHTS = {
    "si_pct_float": 0.35,
    "days_to_cover": 0.25,
    "float_turnover": 0.20,
    "small_float": 0.10,
    "si_trend": 0.10,
}


def squeeze_scores(pos: pd.DataFrame) -> pd.Series:
    """0-100 composite of percentile ranks (NaN components get rank 0.5)."""
    parts = {
        "si_pct_float": pos["si_pct_float"],
        "days_to_cover": pos["days_to_cover"],
        "float_turnover": pos["float_turnover"],
        "small_float": -pos["float_shares"],
        "si_trend": pos["si_trend"],
    }
    total = pd.Series(0.0, index=pos.index)
    for key, series in parts.items():
        rank = series.rank(pct=True).fillna(0.5)
        total = total + WEIGHTS[key] * rank
    return 100.0 * total


def map_squeeze_call(spot: float, implied_move: float, ladder: pd.DataFrame) -> dict | None:
    """Cheapest listed call at/above one implied move up, ask <= $250."""
    target = spot * (1.0 + implied_move)
    calls = ladder[(ladder["strike"] >= target) & (ladder["call_ask"] > 0)].sort_values("strike")
    if calls.empty:  # fall back to the closest OTM call below target
        calls = ladder[(ladder["strike"] > spot) & (ladder["call_ask"] > 0)].sort_values(
            "strike", ascending=False
        )
    for leg in calls.itertuples(index=False):
        cost = float(leg.call_ask) * 100.0
        if 0 < cost <= config.SQUEEZE_MAX_COST:
            return {
                "structure": "long call",
                "detail": f"long {leg.strike:g}C @ ask",
                "entry_side": "debit",
                "entry_price": cost,
                "max_loss": cost,
                "max_gain": float("inf"),
                "strike": float(leg.strike),
                "legs_json": json.dumps(
                    [{"action": "BUY", "right": "CALL", "strike": float(leg.strike)}]
                ),
            }
    return None


def build_squeeze_watch(
    events: pd.DataFrame,
    positioning: pd.DataFrame,
    chains: pd.DataFrame,
    ladders: pd.DataFrame,
    today: date,
) -> pd.DataFrame:
    df = events.merge(positioning, on="ticker", how="inner")
    if df.empty:
        return df
    df["squeeze_score"] = squeeze_scores(df)
    df["candidate"] = (
        (df["si_pct_float"] >= config.SQUEEZE_MIN_SI)
        & (df["squeeze_score"] >= config.SQUEEZE_SCORE_MIN)
    )
    df["squeeze_risk"] = df["si_pct_float"] >= config.SQUEEZE_RISK_SI

    chain_cols = chains.set_index("ticker") if len(chains) else pd.DataFrame()
    rows = []
    for r in df.itertuples(index=False):
        entry = {
            "structure": "watch only", "detail": "", "entry_side": "",
            "entry_price": float("nan"), "max_loss": float("nan"),
            "max_gain": float("nan"), "strike": float("nan"), "legs_json": "",
            "spot": float("nan"), "expiry": "", "implied_move_mid": float("nan"),
            "entry_by": entry_deadline(r.earnings_date, r.session),
        }
        if r.candidate and len(chain_cols) and r.ticker in chain_cols.index:
            ch = chain_cols.loc[r.ticker]
            lad = ladders[(ladders["ticker"] == r.ticker) & (ladders["expiry"] == ch["expiry"])]
            entry.update(
                spot=float(ch["spot"]), expiry=str(ch["expiry"]),
                implied_move_mid=float(ch["implied_move_mid"]),
            )
            mapped = map_squeeze_call(float(ch["spot"]), float(ch["implied_move_mid"]), lad)
            if mapped:
                entry.update(mapped)
            else:
                entry["structure"] = "no affordable call"
        rows.append({**r._asdict(), **entry})
    out = pd.DataFrame(rows).sort_values("squeeze_score", ascending=False).reset_index(drop=True)
    log.info(
        "squeeze watch: %d names, %d candidates (%d with a mapped call), %d flagged squeeze-risk",
        len(out), int(out["candidate"].sum()),
        int((out["structure"] == "long call").sum()), int(out["squeeze_risk"].sum()),
    )
    return out


def run(today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    today = today or date.today()
    events = pd.read_parquet(config.EVENTS_PARQUET)
    positioning = pd.read_parquet(config.POSITIONING_PARQUET)
    chains = pd.read_parquet(config.CHAINS_PARQUET)
    ladders = pd.read_parquet(LADDER_PARQUET)
    out = build_squeeze_watch(events, positioning, chains, ladders, today)
    out.to_parquet(config.SQUEEZE_PARQUET, index=False)
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
