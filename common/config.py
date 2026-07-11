"""Central config: paths, thresholds, and knobs from plan_free_weekend.md.

Every numeric threshold from the plan lives here so a tweak is a one-line
change and the tests can assert against the same constants the code uses.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ETE_DATA_DIR", REPO_ROOT / "data"))
LOG_DIR = REPO_ROOT / "log"

# ---- data artifacts -------------------------------------------------------
UNIVERSE_PARQUET = DATA_DIR / "universe.parquet"
PRICES_PARQUET = DATA_DIR / "prices.parquet"
EVENTS_PARQUET = DATA_DIR / "events_upcoming.parquet"
EARNINGS_HISTORY_PARQUET = DATA_DIR / "earnings_history.parquet"
MOVES_PARQUET = DATA_DIR / "moves.parquet"
FAIR_PARQUET = DATA_DIR / "fair_moves.parquet"
CHAINS_PARQUET = DATA_DIR / "chains.parquet"
SCORED_PARQUET = DATA_DIR / "scored.parquet"
DASHBOARD_DIR = DATA_DIR / "dashboard"
AV_STATE_JSON = DATA_DIR / "av_state.json"
AV_QUEUE_JSON = DATA_DIR / "av_queue.json"
PREDICTIONS_CSV = LOG_DIR / "predictions.csv"

# ---- calendar / history ----------------------------------------------------
CALENDAR_DAYS_AHEAD = 21          # plan §3 block 1: next-21-day calendar
CHAIN_TRADING_DAYS_AHEAD = 10     # plan §3 block 3: chains for next 10 trading days
HISTORY_YEARS = 15                # plan §3 block 1: 15 yrs OHLCV
MIN_HISTORY_QUARTERS = 8          # names with fewer past events -> AV backfill queue
AV_BACKFILL_PRIORITY_DAYS = 10    # plan §2: priority = reporting within 10 days

# ---- Alpha Vantage rationing (plan §2) -------------------------------------
AV_MAX_CALLS_PER_DAY = 25
AV_MIN_SECONDS_BETWEEN_CALLS = 12.5   # 5/min -> one call per 12s; be polite
AV_API_KEY_ENV = "ALPHAVANTAGE_API_KEY"

# ---- fair-move model (plan §3 block 2) --------------------------------------
SHRINKAGE_K = 6                   # w = n / (n + k)
NAME_MAX_QUARTERS = 12            # name-level: last 8-12 quarterly |moves|
RECENCY_HALFLIFE_QUARTERS = 6.0   # recency weighting for the name-level mean
CAP_BUCKET_EDGES_B = (10.0, 50.0, 200.0)  # small/mid/large/mega in $B

# ---- liquidity screen + scoring (plan §3 blocks 3-4) ------------------------
MAX_SPREAD_PCT = 0.10             # drop if straddle spread > 10% of straddle value
SOFT_SPREAD_PCT = 0.08            # liquidity multiplier starts degrading at 8%
MIN_OPEN_INTEREST = 500           # drop if OI < 500 on the event expiry
MAX_LOSS_DOLLARS = 250.0          # defined-risk cap per structure
EDGE_NO_TRADE_BAND = 0.15         # |edge| below this -> "no trade" (v1 default)
MIN_ABS_Z = 1.0                   # and require |z| >= 1 to name a structure

PAPER_ACCOUNT = 10_000.0          # $10k paper account (plan §3 block 4)
RISK_BUDGET_PCT = 0.25            # total max-loss committed at once <= 25% of account
PER_NAME_RISK_CAP = 500.0         # max-loss per underlying (2 contracts at $250)


def ensure_dirs() -> None:
    for d in (DATA_DIR, DASHBOARD_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    return logging.getLogger("ete")
