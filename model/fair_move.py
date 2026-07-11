"""Hierarchical shrinkage fair-move model (plan §3 block 2).

Per upcoming reporter:
  * name level  — recency-weighted mean of the last NAME_MAX_QUARTERS
    quarterly |moves| (exponential weights, halflife 6 quarters).
  * pool level  — sector × market-cap-bucket average of the name-level
    means; pools with <3 names fall back to sector, then to the global pool.
  * blend       — empirical-Bayes shrinkage, w = n / (n + k), k = 6:
    fair = w * name_mean + (1 - w) * pool_mean.
  * rough CI    — se = blended sigma / sqrt(n + k); 80% band at ±1.2816 se.
    "Rough" is the design goal (plan block 4): it only feeds the edge z-score.
  * tails       — scaled-t per name for the long-vol EV model: per-name fit
    (scipy t, loc=0) when n >= 8, otherwise global df fitted on pooled
    standardized moves with the scale backed out so E|move| matches fair.

Sanity harness (plan block 2): hold out each name's most recent move, refit
on the rest, and compare predictions to what actually happened.
  uv run python -m model.fair_move --sanity

Output: data/fair_moves.parquet
"""

from __future__ import annotations

import logging
import math

import numpy as np
import pandas as pd
from scipy import stats

from common import config

log = logging.getLogger("ete.fair_move")

Z80 = 1.2816  # two-sided 80% normal quantile

FAIR_COLUMNS = [
    "ticker", "fair_move", "ci_low", "ci_high", "n_events", "w_name",
    "name_mean", "pool", "pool_mean", "t_nu", "t_scale", "low_conf_share",
]

CAP_LABELS = ("small", "mid", "large", "mega")


def cap_bucket(cap_b: float) -> str:
    if cap_b is None or not np.isfinite(cap_b):
        return "unknown"
    for edge, label in zip(config.CAP_BUCKET_EDGES_B, CAP_LABELS):
        if cap_b < edge:
            return label
    return CAP_LABELS[-1]


def _recency_weights(n: int) -> np.ndarray:
    """Weights for events ordered oldest -> newest; newest gets weight 1."""
    ages = np.arange(n - 1, -1, -1, dtype=float)  # newest has age 0
    return 0.5 ** (ages / config.RECENCY_HALFLIFE_QUARTERS)


def _t_abs_mean(nu: float) -> float:
    """E|T| for a standard t with df nu (finite for nu > 1)."""
    return (
        2.0 * math.sqrt(nu) * math.gamma((nu + 1) / 2)
        / (math.sqrt(math.pi) * (nu - 1) * math.gamma(nu / 2))
    )


def _fit_global_nu(moves: pd.DataFrame) -> float:
    """t df fitted on all names' standardized signed moves, clipped sane."""
    zs = []
    for _, g in moves.groupby("ticker"):
        if len(g) < 4:
            continue
        s = g["move"].std(ddof=1)
        if s and np.isfinite(s) and s > 0:
            zs.append(g["move"].to_numpy() / s)
    if not zs:
        return 5.0  # literature-ish prior for earnings moves
    z = np.concatenate(zs)
    try:
        nu, _, _ = stats.t.fit(z, floc=0)
    except Exception:
        return 5.0
    return float(np.clip(nu, 2.1, 30.0))


def _name_stats(moves: pd.DataFrame) -> pd.DataFrame:
    """Per-name recency-weighted mean/std of |move| over the recent window."""
    rows = []
    for ticker, g in moves.groupby("ticker"):
        g = g.sort_values("event_date").tail(config.NAME_MAX_QUARTERS)
        absm = g["abs_move"].to_numpy(dtype=float)
        w = _recency_weights(len(absm))
        mean = float(np.average(absm, weights=w))
        std = float(absm.std(ddof=1)) if len(absm) >= 2 else np.nan
        rows.append(
            {
                "ticker": ticker,
                "name_mean": mean,
                "name_std": std,
                "n_events": len(absm),
                "low_conf_share": float((g["confidence"] == "low").mean()),
                "signed_recent": g["move"].to_numpy(dtype=float),
            }
        )
    return pd.DataFrame(rows)


def estimate_fair_moves(moves: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Fair |move| per upcoming reporter (every ticker in `events`)."""
    events = events.copy()
    events["bucket"] = events["cap_b"].map(cap_bucket) if "cap_b" in events else "unknown"

    stats_df = _name_stats(moves) if not moves.empty else pd.DataFrame(
        columns=["ticker", "name_mean", "name_std", "n_events", "low_conf_share", "signed_recent"]
    )
    merged = events.merge(stats_df, on="ticker", how="left")
    merged["n_events"] = merged["n_events"].fillna(0).astype(int)

    # pools built from name-level means so heavy reporters don't dominate
    with_stats = merged[merged["n_events"] > 0]
    sector_bucket = with_stats.groupby(["sector", "bucket"])["name_mean"].agg(["mean", "std", "count"])
    sector_only = with_stats.groupby("sector")["name_mean"].agg(["mean", "std", "count"])
    global_mean = float(with_stats["name_mean"].mean()) if len(with_stats) else 0.05
    global_std = float(with_stats["name_mean"].std(ddof=1)) if len(with_stats) > 1 else 0.02

    global_nu = _fit_global_nu(moves) if not moves.empty else 5.0

    rows = []
    for row in merged.itertuples(index=False):
        # ---- pool selection with fallbacks -------------------------------
        pool_name, pool_mean, pool_std = "global", global_mean, global_std
        key = (row.sector, row.bucket)
        if key in sector_bucket.index and sector_bucket.loc[key, "count"] >= 3:
            pool_name = f"{row.sector}|{row.bucket}"
            pool_mean = float(sector_bucket.loc[key, "mean"])
            pool_std = float(sector_bucket.loc[key, "std"])
        elif row.sector in sector_only.index and sector_only.loc[row.sector, "count"] >= 3:
            pool_name = str(row.sector)
            pool_mean = float(sector_only.loc[row.sector, "mean"])
            pool_std = float(sector_only.loc[row.sector, "std"])
        if not np.isfinite(pool_std) or pool_std <= 0:
            pool_std = global_std if np.isfinite(global_std) and global_std > 0 else 0.02

        # ---- empirical-Bayes blend, w = n/(n+k) --------------------------
        n = int(row.n_events)
        w = n / (n + config.SHRINKAGE_K)
        name_mean = float(row.name_mean) if n > 0 else 0.0
        fair = w * name_mean + (1 - w) * pool_mean

        name_std = float(row.name_std) if n >= 2 and np.isfinite(row.name_std) else pool_std
        sigma = w * name_std + (1 - w) * pool_std
        se = sigma / math.sqrt(n + config.SHRINKAGE_K)
        ci_low, ci_high = max(fair - Z80 * se, 0.0), fair + Z80 * se

        # ---- scaled-t tail model -----------------------------------------
        nu, scale = global_nu, fair / _t_abs_mean(global_nu)
        signed = row.signed_recent if isinstance(row.signed_recent, np.ndarray) else np.array([])
        if n >= 8:
            try:
                nu_fit, _, scale_fit = stats.t.fit(signed, floc=0)
                if np.isfinite(nu_fit) and np.isfinite(scale_fit) and scale_fit > 0:
                    nu = float(np.clip(nu_fit, 2.1, 30.0))
                    scale = float(scale_fit)
            except Exception:
                pass  # keep the global fallback

        rows.append(
            {
                "ticker": row.ticker,
                "fair_move": fair,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "n_events": n,
                "w_name": w,
                "name_mean": name_mean,
                "pool": pool_name,
                "pool_mean": pool_mean,
                "t_nu": nu,
                "t_scale": scale,
                "low_conf_share": float(row.low_conf_share) if n > 0 else 1.0,
            }
        )
    return pd.DataFrame(rows, columns=FAIR_COLUMNS)


# ------------------------------------------------------------ sanity harness
def sanity_harness(moves: pd.DataFrame, events: pd.DataFrame, min_events: int = 4) -> dict:
    """Leave-latest-out calibration check (plan block 2: 'eyeball it').

    For each name with >= min_events moves: drop its most recent move, refit
    the whole model, and compare the prediction to the held-out |move|.
    Prints a per-name table plus summary stats; returns the summary.
    """
    eligible = [t for t, g in moves.groupby("ticker") if len(g) >= min_events]
    rows = []
    for ticker in eligible:
        g = moves[moves["ticker"] == ticker].sort_values("event_date")
        held = g.iloc[-1]
        train = pd.concat([moves[moves["ticker"] != ticker], g.iloc[:-1]], ignore_index=True)
        fair = estimate_fair_moves(train, events[events["ticker"] == ticker])
        if fair.empty:
            continue
        f = fair.iloc[0]
        t_p80 = stats.t.ppf(0.90, f["t_nu"]) * f["t_scale"]  # 80% two-sided band on |move|
        rows.append(
            {
                "ticker": ticker,
                "fair_est": f["fair_move"],
                "actual_abs": held["abs_move"],
                "ratio": held["abs_move"] / f["fair_move"] if f["fair_move"] > 0 else np.nan,
                "inside_ci": f["ci_low"] <= held["abs_move"] <= f["ci_high"],
                "inside_t80": held["abs_move"] <= t_p80,
            }
        )
    table = pd.DataFrame(rows)
    if table.empty:
        log.warning("sanity harness: no names with >= %d events", min_events)
        return {"n_names": 0}
    summary = {
        "n_names": len(table),
        "median_ratio": float(table["ratio"].median()),
        "mean_ratio": float(table["ratio"].mean()),
        "share_inside_t80": float(table["inside_t80"].mean()),
    }
    with pd.option_context("display.float_format", "{:0.4f}".format, "display.max_rows", 200):
        print(table.sort_values("ratio").to_string(index=False))
    print(
        f"\nsanity: {summary['n_names']} names | actual/fair median "
        f"{summary['median_ratio']:.2f} (want ~1) | mean {summary['mean_ratio']:.2f} "
        f"| inside t-80% band {100 * summary['share_inside_t80']:.0f}% (want ~80%)"
    )
    return summary


def run(moves: pd.DataFrame | None = None, events: pd.DataFrame | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if moves is None:
        moves = pd.read_parquet(config.MOVES_PARQUET)
    if events is None:
        events = pd.read_parquet(config.EVENTS_PARQUET)
    fair = estimate_fair_moves(moves, events)
    fair.to_parquet(config.FAIR_PARQUET, index=False)
    log.info(
        "fair moves for %d reporters (median %.2f%%) -> %s",
        len(fair), 100 * fair["fair_move"].median() if len(fair) else float("nan"),
        config.FAIR_PARQUET,
    )
    return fair


if __name__ == "__main__":
    import sys

    config.setup_logging()
    if "--sanity" in sys.argv:
        sanity_harness(pd.read_parquet(config.MOVES_PARQUET), pd.read_parquet(config.EVENTS_PARQUET))
    else:
        run()
