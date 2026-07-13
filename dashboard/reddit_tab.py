"""'Reddit Suggestions' dashboard tab (plan_reddit_growth).

Shows the Stage A calibration up top (why Reddit is a scout, not a signal),
theme-level crowding, then the ranked constraint ideas with sleeves, gates,
and memo modals. Guard text stays on the page.
"""

from __future__ import annotations

import html

import numpy as np
import pandas as pd

from common import config
from dashboard.value_tab import md_to_html


def _meter(value: float, lo: float = 0.0, hi: float = 100.0) -> str:
    if value is None or not np.isfinite(value):
        return '<span class=muted>—</span>'
    pct = max(0.0, min(1.0, (value - lo) / (hi - lo))) * 100
    return (
        f'<span class=meter aria-hidden=true><span class=meterfill '
        f'style="width:{pct:.0f}%"></span></span>'
    )

GUARD = (
    "Reddit is the idea funnel and crowding gauge here — never a buy signal. "
    "The Stage A autopsy showed cohort returns are mostly beta and momentum with heavy "
    "two-name concentration; positions come only from constraint evidence that passes gates."
)


def _sv(v) -> str:
    return f"{v:.3f}" if v is not None and np.isfinite(v) else "-999"


def render_reddit_tab(
    ideas: pd.DataFrame | None,
    gates: pd.DataFrame | None,
    theme_summary: pd.DataFrame | None,
    memos_by_ticker: dict[str, str] | None = None,
    autopsy_summary: str = "",
) -> str:
    intro = (
        "<h2>Reddit Suggestions — constraint ideas from the crowd's themes</h2>"
        f"<p class=muted>{html.escape(GUARD)} Full numbers in "
        '<a href="reports/cohort_autopsy.md">reports/cohort_autopsy.md</a>.</p>'
    )
    if autopsy_summary:
        intro += f'<div class=howto><strong>Stage A in one line:</strong> {html.escape(autopsy_summary)}</div>'
    if ideas is None or ideas.empty:
        return intro + "<p class=muted>No gated ideas yet — run <code>make ideas</code>.</p>"

    memos_by_ticker = memos_by_ticker or {}
    tiles = "".join(
        f'<div class=tile><div class=v>{v}</div><div class=k>{k}</div></div>'
        for v, k in [
            (len(gates) if gates is not None else 0, "candidates gated"),
            (int(gates["gates_passed"].sum()) if gates is not None else 0, "pass all gates"),
            (len(ideas), "quiet-equity ideas"),
            (ideas["theme"].nunique(), "themes active (max 3)"),
        ]
    )

    theme_html = ""
    if theme_summary is not None and len(theme_summary):
        rows = "".join(
            f"<tr><td>{html.escape(str(r.theme))}</td>"
            f"<td class=num data-v={r.mentions}>{r.mentions}</td>"
            f"<td class=num data-v={_sv(r.max_velocity_z)}>{r.max_velocity_z:+.2f}</td>"
            f"<td class=muted>{html.escape(str(r.tickers))}</td></tr>"
            for r in theme_summary.head(10).itertuples(index=False)
        )
        theme_html = (
            "<h3>Theme crowding (live mentions)</h3>"
            '<div class=tablewrap><table class=sortable>'
            "<tr><th>Theme</th><th data-s=1>Mentions</th><th data-s=1>Max velocity z</th>"
            "<th>Loudest tickers</th></tr>" + rows + "</table></div>"
        )

    cards, templates = [], []
    for r in ideas.itertuples(index=False):
        tkey = f"gmemo-{r.ticker}"
        memo_btn = ""
        if r.ticker in memos_by_ticker:
            memo_btn = (
                f'<button class="memobtn" data-memo="{tkey}">open thesis memo 📝</button>'
            )
            templates.append(
                f'<template id="{tkey}">{md_to_html(memos_by_ticker[r.ticker])}</template>'
            )
        gates_line = html.escape(str(r.gate_notes))
        access = f'<div class=srow>⚠️ {html.escape(str(r.access_flag))}</div>' if r.access_flag else ""
        cards.append(f"""
<div class=card>
  <div class=cardhead><span class=tkbig>{html.escape(str(r.ticker))}</span>
    <span class=verb>{html.escape(str(r.theme))} · {html.escape(str(r.kind))}</span></div>
  <div class=muted>{html.escape(str(r.name))} · node: {html.escape(str(r.node))}
      · evidence items: {int(r.n_evidence)} · confidence: {html.escape(str(r.confidence))}</div>
  <div class=srow>Crowding z: <strong>{r.crowding_z:+.2f}</strong>
      ({int(r.crowding_n_inputs)} input{'s' if r.crowding_n_inputs != 1 else ''})
      {_meter(float(np.clip(50 + 25 * r.crowding_z, 0, 100)))}
      · gates: <strong>{gates_line}</strong></div>
  <div class=srow>{html.escape(str(r.exposure))}</div>
  {access}
  <div class=money>Sleeve: <strong>quiet-equity</strong> · max ${r.max_position_dollars:,.0f}
      (5% of book) · barbell vs {html.escape(str(r.barbell_against))}</div>
  {memo_btn}
</div>""")

    options_note = (
        "<h3>Options sleeve (crowded names → engine #1)</h3>"
        "<p class=muted>Crowded first-order names are exported to "
        "<code>data/options_sleeve.csv</code>; when they enter the earnings window, the "
        "Trade plan tab prices them as defined-risk structures (max loss ≤ $250) instead "
        "of stock — elevated IV and crowding make structure beat direction there.</p>"
    )
    return (
        intro + f"<div class=tiles>{tiles}</div>" + theme_html
        + "<h3>Ranked quiet-constraint ideas (paper)</h3>"
        + f"<div class=cards>{''.join(cards)}</div>"
        + options_note + "".join(templates)
    )
