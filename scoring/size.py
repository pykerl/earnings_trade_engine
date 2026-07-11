"""$10k paper-account allocation: which structures to order, and how many.

Rules (v1, deliberately simple and explainable):
  * only unscreened, actionable structures whose entry window is still open,
  * one position per company (GOOGL/GOOG style share classes deduped —
    highest |score| class wins),
  * contracts per name: as many as fit PER_NAME_RISK_CAP ($500 of max loss,
    i.e. up to 2 of a $250-max-loss structure),
  * fill in |score| order until the committed max-loss reaches
    RISK_BUDGET_PCT x account ($2,500 of $10k) — partial fills allowed,
    then stop.

Paper trading only (plan: no real sizing until the season-end review).
"""

from __future__ import annotations

import logging
import math
import re
from datetime import date

import pandas as pd

from common import config
from scoring.rank import next_trading_session

log = logging.getLogger("ete.size")

ACTIONABLE = ("iron fly", "long straddle", "long strangle")


def company_key(name: str, ticker: str) -> str:
    """Collapse share classes: 'Alphabet Inc. (Class A)' == '... (Class C)'."""
    base = re.sub(r"\s*\((class|series)\s+[a-z0-9]+\)\s*$", "", str(name or ""), flags=re.I)
    base = base.strip().lower()
    return base or str(ticker)


def build_trade_plan(
    scored: pd.DataFrame,
    today: date,
    account: float = config.PAPER_ACCOUNT,
    risk_budget_pct: float = config.RISK_BUDGET_PCT,
    per_name_cap: float = config.PER_NAME_RISK_CAP,
) -> pd.DataFrame:
    """Returns the plan (one row per position) with contracts and totals."""
    if scored.empty:
        return pd.DataFrame()
    next_session = next_trading_session(today)
    cand = scored[
        (~scored["screened"])
        & scored["structure"].isin(ACTIONABLE)
        & (pd.to_datetime(scored["entry_by"]).dt.date >= next_session)
    ].copy()
    if cand.empty:
        return pd.DataFrame()

    cand["company"] = [company_key(r.name, r.ticker) for r in cand.itertuples(index=False)]
    cand = (
        cand.sort_values("score", key=lambda s: s.abs(), ascending=False)
        .drop_duplicates("company")
    )

    budget = account * risk_budget_pct
    committed = 0.0
    rows = []
    for r in cand.itertuples(index=False):
        if not (r.max_loss and r.max_loss > 0):
            continue
        want = max(1, math.floor(per_name_cap / r.max_loss))
        fits = math.floor((budget - committed) / r.max_loss)
        contracts = min(want, fits)
        if contracts < 1:
            break  # budget exhausted (list is score-ordered; nothing smaller matters)
        committed += contracts * r.max_loss
        rows.append(
            {
                "ticker": r.ticker,
                "name": r.name,
                "structure": r.structure,
                "contracts": contracts,
                "entry_side": r.entry_side,
                "entry_price": r.entry_price,          # $ per contract
                "cash_flow": (1 if r.entry_side == "credit" else -1) * r.entry_price * contracts,
                "position_risk": contracts * r.max_loss,
                "position_max_gain": (
                    float("inf") if r.max_gain == float("inf") else contracts * r.max_gain
                ),
                "entry_by": r.entry_by,
                "earnings_date": r.earnings_date,
                "session": r.session,
                "expiry": r.expiry,
                "spot": r.spot,
                "legs_json": r.legs_json,
                "edge": r.edge,
                "score": r.score,
                "implied_move_mid": r.implied_move_mid,
                "fair_move": r.fair_move,
                "n_events": r.n_events,
            }
        )
    plan = pd.DataFrame(rows)
    if len(plan):
        log.info(
            "trade plan: %d positions, $%.0f max-loss committed of $%.0f budget",
            len(plan), committed, budget,
        )
    return plan
