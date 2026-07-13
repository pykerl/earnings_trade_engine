"""Eight-section constraint-thesis memos (plan_reddit_growth §6)."""

from __future__ import annotations

import logging
from datetime import date

import pandas as pd
from jinja2 import Environment, FileSystemLoader

from common import config
from gates.growth_gates import load_constraint_map
from memos.generator import write_memo

log = logging.getLogger("ete.growth_memos")


def exit_triggers(node: dict, row: pd.Series) -> list[str]:
    out = [
        f"Capacity watch fires: {node.get('capacity_watch', 'announced capacity lands')} — "
        "constraint resolving = thesis expiring (these are 1-3yr theses, not holds)",
        "Two consecutive prints without backlog/lead-time/pricing evidence strengthening",
        "Design-out or architecture shift removing the node from the bottleneck path",
        "Crowding z of this name rises above +1.5 (the quiet node is no longer quiet)",
    ]
    if row.get("gate_dilution") is False:
        out.append("Dilution accelerates further (already the weakest gate)")
    return out


def earnings_note(ticker: str, events: pd.DataFrame | None) -> str:
    if events is not None and len(events):
        hit = events[events["ticker"] == ticker]
        if len(hit):
            ev = hit.iloc[0]
            return (
                f"Reports {ev['earnings_date']} ({ev['session']}). One print can confirm or "
                "weaken the backlog/lead-time evidence; it cannot prove the multi-year "
                "constraint thesis. Watch the pre-registered evidence items, not the EPS beat."
            )
    return (
        "No confirmed report date in the current 21-day calendar window. The thesis rests "
        "on constraint evidence, not the next print."
    )


def generate(
    ideas: pd.DataFrame,
    events: pd.DataFrame | None,
    top_n: int = 8,
    memo_date: date | None = None,
) -> list[str]:
    memo_date = memo_date or date.today()
    nodes = load_constraint_map()
    env = Environment(loader=FileSystemLoader(config.MEMOS_DIR), autoescape=False)
    template = env.get_template("growth_template.md.j2")
    paths = []
    for _, row in ideas.head(top_n).iterrows():
        node = nodes[row["node"]]
        content = template.render(
            memo_date=memo_date.isoformat(),
            constraint_text=str(node["constraint"]).strip(),
            evidence=node.get("evidence", []),
            exit_triggers=exit_triggers(node, row),
            earnings_note=earnings_note(row["ticker"], events),
            **{k: row[k] for k in row.index},
        )
        paths.append(write_memo(f"{row['ticker']}_growth", content, memo_date))
    log.info("wrote %d growth memos", len(paths))
    return paths
