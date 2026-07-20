"""'Scorecard' tab: what worked and what didn't, updated every daily run.

Renders reports/options_scorecard.md (the single source of truth written by
scoring/score_log.py) plus summary tiles from the scored parquet.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from common import config
from dashboard.value_tab import md_to_html

SCORECARD_MD = config.REPO_ROOT / "reports" / "options_scorecard.md"


def render_scorecard_tab(scored: pd.DataFrame | None) -> str:
    intro = (
        "<h2>Scorecard — the experiment, scored</h2>"
        "<p class=muted>Every pre-registered event, evaluated after it resolved: frozen "
        "prices, expiry settlement, no revisions. Losses stay on the page — that is the "
        "point of the journal.</p>"
    )
    if scored is None or scored.empty or not SCORECARD_MD.exists():
        return intro + "<p class=muted>No resolved events yet — check back after the next prints.</p>"

    traded = scored[scored["pnl"].notna()]
    hyp = scored[scored["model_aligned_pnl"].notna()]
    tiles = "".join(
        f'<div class=tile><div class=v>{v}</div><div class=k>{k}</div></div>'
        for v, k in [
            (len(scored), "events resolved"),
            (f"{100 * scored['inside_implied'].mean():.0f}%", "landed inside implied"),
            (f"${traded['pnl'].sum():,.0f}" if len(traded) else "—",
             f"traded P&L ({len(traded)} structures)"),
            (f"${hyp['model_aligned_pnl'].sum():,.0f}" if len(hyp) else "—",
             "model-aligned hypothetical P&L"),
        ]
    )
    return intro + f"<div class=tiles>{tiles}</div>" + (
        f'<div class=memo-body>{md_to_html(SCORECARD_MD.read_text())}</div>'
    )
