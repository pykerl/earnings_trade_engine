"""Three-sleeve position construction (plan_reddit_growth §5).

Sleeves:
  1. quiet constraint owner, direct equity — gate-passing, low crowding;
  2. crowded name, defined-risk options expression — EXPORTED to engine #1
     (data/options_sleeve.csv) rather than re-implementing options logic;
  3. barbell — long the quiet node vs structurally underweighting the
     crowded first-order name of the same theme.

Crowding score per §3.B3: mean of available z-inputs — Reddit mention
velocity, short-interest %, EV/S-vs-growth percentile within theme — with
the component count recorded (honest about thin inputs).

Portfolio rules encoded: max 3 themes, max 2 positions per theme,
single-name max risk 5% of the $10k research book, foreign listings
flagged. Paper only.

Output: data/growth_ideas.parquet + data/options_sleeve.csv
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.construct")

RESEARCH_BOOK = 10_000.0
SINGLE_NAME_RISK = 0.05          # 5% of book
MAX_THEMES = 3
MAX_PER_THEME = 2
CROWDED_Z = 1.0                  # velocity z above this = crowded


def crowding_scores(
    tickers: pd.Series,
    mentions: pd.DataFrame | None,
    positioning: pd.DataFrame | None,
) -> pd.DataFrame:
    out = pd.DataFrame({"ticker": tickers})
    if mentions is not None and len(mentions):
        out = out.merge(
            mentions[["ticker", "mentions", "velocity_z", "velocity_mode"]],
            on="ticker", how="left",
        )
    else:
        out["mentions"], out["velocity_z"], out["velocity_mode"] = 0, np.nan, "none"
    if positioning is not None and len(positioning):
        si = positioning.set_index("ticker")["si_pct_float"]
        out["si_pct_float"] = out["ticker"].map(si)
    else:
        out["si_pct_float"] = np.nan

    comps = pd.DataFrame(index=out.index)
    comps["velocity"] = out["velocity_z"]
    si = out["si_pct_float"]
    comps["short_interest"] = (si - si.mean()) / si.std(ddof=1) if si.notna().sum() >= 3 else np.nan
    out["crowding_n_inputs"] = comps.notna().sum(axis=1)
    out["crowding_z"] = comps.mean(axis=1, skipna=True).fillna(0.0)
    return out


def build_ideas(
    gates: pd.DataFrame,
    mentions: pd.DataFrame | None = None,
    positioning: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (ranked equity/barbell ideas, options-sleeve export)."""
    crowd = crowding_scores(gates["ticker"], mentions, positioning)
    df = gates.merge(crowd, on="ticker", how="left")

    # -------- sleeve 2: crowded first-order names -> engine #1 -------------
    crowded_rows = []
    for node, g in df.groupby("node"):
        for t in str(g.iloc[0]["crowded_names"]).split(","):
            t = t.strip()
            if t:
                crowded_rows.append(
                    {"ticker": t, "node": node, "theme": g.iloc[0]["theme"],
                     "sleeve": "options",
                     "note": "crowded first-order name — route through engine #1 "
                             "(defined-risk, max loss <= $250)"}
                )
    options_sleeve = pd.DataFrame(crowded_rows).drop_duplicates("ticker")

    # -------- sleeves 1 & 3: gate-passing quiet nodes ----------------------
    eligible = df[df["gates_passed"] & (df["crowding_z"] < CROWDED_Z)].copy()
    eligible["idea_score"] = (
        eligible["confidence"].map({"high": 1.0, "medium": 0.6}).fillna(0.5)
        * (1 + eligible["n_evidence"].clip(upper=5) / 5)
        * (1 - eligible["crowding_z"].clip(-2, 2) / 4)
        * np.where(eligible["kind"] == "pure_play", 1.15, 1.0)
    )
    eligible = (
        eligible.sort_values("idea_score", ascending=False)
        .drop_duplicates("ticker")  # a ticker in two nodes is still one position
    )
    eligible["velocity_mode"] = eligible["velocity_mode"].fillna("no mention data")

    picks, theme_counts = [], {}
    for _, r in eligible.iterrows():
        theme = r["theme"]
        if len({p["theme"] for p in picks}) >= MAX_THEMES and theme not in {p["theme"] for p in picks}:
            continue
        if theme_counts.get(theme, 0) >= MAX_PER_THEME:
            continue
        theme_counts[theme] = theme_counts.get(theme, 0) + 1
        crowded = str(r["crowded_names"]).split(",")[0].strip()
        picks.append(
            {
                **r.to_dict(),
                "sleeve": "quiet_equity",
                "max_position_dollars": RESEARCH_BOOK * SINGLE_NAME_RISK,
                "barbell_against": crowded,
                "barbell_note": (
                    f"long {r['ticker']} vs structurally underweight {crowded} — "
                    "captures 'alpha migrates upstream' and hedges theme drawdown"
                ),
                "access_flag": "" if str(r["listing"]).startswith("US") and "ADR" not in str(r["listing"])
                else f"ACCESS: {r['listing']}",
            }
        )
    ideas = pd.DataFrame(picks)
    log.info(
        "ideas: %d quiet-equity picks across %d themes; %d options-sleeve exports",
        len(ideas), len(theme_counts), len(options_sleeve),
    )
    return ideas, options_sleeve


def run() -> pd.DataFrame:
    config.ensure_dirs()
    gates = pd.read_parquet(config.DATA_DIR / "growth_gates.parquet")
    mentions = (
        pd.read_parquet(config.DATA_DIR / "mentions_latest.parquet")
        if (config.DATA_DIR / "mentions_latest.parquet").exists() else None
    )
    positioning = (
        pd.read_parquet(config.POSITIONING_PARQUET)
        if config.POSITIONING_PARQUET.exists() else None
    )
    ideas, options_sleeve = build_ideas(gates, mentions, positioning)
    ideas.to_parquet(config.DATA_DIR / "growth_ideas.parquet", index=False)
    options_sleeve.to_csv(config.DATA_DIR / "options_sleeve.csv", index=False)
    return ideas


if __name__ == "__main__":
    config.setup_logging()
    run()
