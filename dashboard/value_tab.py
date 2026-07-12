"""Value-engine dashboard tabs (plan_value.md §6) for the shared page.

Tab "Value screen": full ranked list (quality-gated margin of safety).
Tab "Value: reporting soon": the earnings-season overlay with its two modes
kept separate — conviction entries vs overreaction watch — and the
anti-pattern guard stated on the page itself.
"""

from __future__ import annotations

import html
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import config

GUARD = (
    "Anti-pattern guard: this process never buys BECAUSE earnings are coming. "
    "A quarter is noise against a 10-year owner-earnings record; the report date "
    "matters only when a fearful print creates the margin of safety that wasn't there."
)


def _sv(v) -> str:
    return f"{v:.3f}" if v is not None and np.isfinite(v) else "-999"


def _pct(v, digits=0) -> str:
    return f"{100 * v:.{digits}f}%" if v is not None and np.isfinite(v) else "—"


def _first_sentence(text: str) -> str:
    return text.split(". ")[0].strip() + "."


def render_value_screen(vals: pd.DataFrame | None, insiders: pd.DataFrame | None = None,
                        gurus: pd.DataFrame | None = None) -> str:
    intro = (
        "<h2>Value screen — wonderful companies at fair prices</h2>"
        "<p class=muted>Quality gates run before cheapness: moat footprints (10-yr ROIC "
        "without leverage), Munger disqualifiers, THEN margin of safety = discount to the "
        "most conservative of three lenses. Owner earnings use the stated maintenance-capex "
        f"proxy. Research output, not advice. {html.escape(GUARD)}</p>"
    )
    if vals is None or vals.empty:
        return intro + "<p class=muted>No valuation data yet — run <code>make weekly</code>.</p>"
    cluster = set(insiders[insiders["cluster_buy"]]["ticker"]) if insiders is not None and len(insiders) else set()
    guru_names = (
        gurus.groupby("ticker")["holder"].apply(lambda s: ", ".join(sorted(set(s)))).to_dict()
        if gurus is not None and len(gurus) else {}
    )
    show = vals[vals["verdict"].isin(["buy candidate", "watch (needs price)"])].head(60)
    rows = []
    for i, r in enumerate(show.itertuples(index=False), 1):
        marks = []
        if r.ticker in cluster:
            marks.append("insider cluster buy")
        if r.ticker in guru_names:
            marks.append(f"held: {guru_names[r.ticker]}")
        if r.needs_human_review:
            marks.append("needs human review")
        rows.append(
            f"<tr><td class=num>{i}</td>"
            f"<td class=tk><strong>{html.escape(str(r.ticker))}</strong></td>"
            f"<td>{html.escape(str(r.verdict))}</td>"
            f"<td data-v={_sv(r.margin_of_safety)} class=num><strong>{_pct(r.margin_of_safety)}</strong></td>"
            f"<td data-v={_sv(r.oe_yield)} class=num>{_pct(r.oe_yield, 1)}</td>"
            f"<td data-v={_sv(r.roic_median_10y)} class=num>{_pct(r.roic_median_10y)}</td>"
            f"<td data-v={_sv(r.implied_growth)} class=num>{_pct(r.implied_growth, 1)} "
            f"<span class=muted>vs {_pct(r.rev_cagr_10y, 1)}</span></td>"
            f"<td data-v={_sv(r.nd_ebitda)} class=num>{f'{r.nd_ebitda:.1f}' if np.isfinite(r.nd_ebitda) else 'net cash'}</td>"
            f"<td class=flags>{html.escape(r.demote_reasons or '')}</td>"
            f"<td class=flags>{html.escape('; '.join(marks))}</td></tr>"
        )
    n_buy = int((vals["verdict"] == "buy candidate").sum())
    n_watch = int((vals["verdict"] == "watch (needs price)").sum())
    n_eject = int(vals["eject"].sum())
    tiles = "".join(
        f'<div class=tile><div class=v>{v}</div><div class=k>{k}</div></div>'
        for v, k in [
            (len(vals), "companies valued"), (n_buy, "buy candidates"),
            (n_watch, "watch list"), (n_eject, "ejected by disqualifiers"),
        ]
    )
    return intro + f"<div class=tiles>{tiles}</div>" + (
        '<div class=tablewrap><table class=sortable>'
        "<tr><th>#</th><th>Ticker</th><th>Verdict</th><th data-s=1>Margin of safety</th>"
        "<th data-s=1>OE yield</th><th data-s=1>ROIC 10y med</th>"
        "<th data-s=1>Implied vs hist growth</th><th data-s=1>ND/EBITDA</th>"
        "<th>Demotions</th><th>Marks</th></tr>"
        f"{''.join(rows)}</table></div>"
        "<p class=muted>Memos for the top candidates live in <code>memos/</code> in the repo "
        "(git-versioned, human review pending). Full list incl. ejections in the CSV.</p>"
    )


def render_reporting_soon(
    vals: pd.DataFrame | None,
    events: pd.DataFrame | None,
    today: date | None = None,
    thesis_fn=None,
) -> str:
    intro = (
        "<h2>Undervalued &amp; reporting soon</h2>"
        f"<p class=muted><strong>{html.escape(GUARD)}</strong></p>"
    )
    if vals is None or vals.empty or events is None or events is None or len(events) == 0:
        return intro + "<p class=muted>Needs both the value screen and the earnings calendar.</p>"
    today = today or date.today()
    horizon = today + timedelta(days=21)
    ev = events[
        (pd.to_datetime(events["earnings_date"]).dt.date >= today)
        & (pd.to_datetime(events["earnings_date"]).dt.date <= horizon)
    ]
    joined = vals.merge(ev[["ticker", "earnings_date", "session"]], on="ticker", how="inner")

    def block(title: str, sub: str, frame: pd.DataFrame, watch_mode: bool) -> str:
        if frame.empty:
            return f"<h3>{title}</h3><p class=muted>{sub}</p><p class=muted>None this window.</p>"
        rows = []
        for r in frame.itertuples(index=False):
            thesis = _first_sentence(thesis_fn(pd.Series(r._asdict()))) if thesis_fn else ""
            if watch_mode and np.isfinite(r.value_conservative) and r.market_cap > 0:
                need = 1 - (r.value_conservative * (1 - config.MOS_BUY)) / r.market_cap
                interest = (
                    f"interested if price falls ≥ {100 * max(need, 0):.0f}% (pre-set now, execute mechanically)"
                    if need > 0 else "already at an interesting price — re-check the gates"
                )
            else:
                interest = "would own regardless of the print; earnings is just the next data point"
            rows.append(
                f"<tr><td class=tk><strong>{html.escape(str(r.ticker))}</strong></td>"
                f"<td>{r.earnings_date} <span class=muted>{html.escape(str(r.session))}</span></td>"
                f"<td class=num>{_pct(r.margin_of_safety)}</td>"
                f"<td>{html.escape(thesis)}</td>"
                f"<td>{html.escape(interest)}</td></tr>"
            )
        return (
            f"<h3>{title}</h3><p class=muted>{sub}</p>"
            '<div class=tablewrap><table>'
            "<tr><th>Ticker</th><th>Reports</th><th>MoS</th><th>Thesis one-liner</th><th>Stance</th></tr>"
            f"{''.join(rows)}</table></div>"
        )

    conviction = joined[joined["verdict"] == "buy candidate"]
    overreaction = joined[joined["verdict"] == "watch (needs price)"]
    return intro + block(
        "Conviction entries",
        "Already-passed candidates; you'd buy regardless of the print.",
        conviction, watch_mode=False,
    ) + block(
        "Overreaction watch",
        "Quality names where a fearful post-earnings drop could create the margin of safety.",
        overreaction, watch_mode=True,
    )
