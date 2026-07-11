"""Ranked daily dashboard: HTML + CSV (plan §3 block 4).

Columns (every one from Block 4): ticker, earnings date/time, implied move
(mid & ask), fair move ± CI, edge %, structure, max gain/loss, spread cost as
% of edge, confidence, sample size, flags.

The HTML shows the ranked live list first and the liquidity-screen kill list
below it (the screen eating a third of the list is the model working). The
CSV carries all rows plus the raw numeric fields for later analysis.
"""

from __future__ import annotations

import html
import json
import logging
from datetime import date

import numpy as np
import pandas as pd

from common import config
from dashboard import charts

log = logging.getLogger("ete.dashboard")

CSV_COLUMNS = [
    "ticker", "name", "sector", "earnings_date", "session", "entry_by",
    "implied_move_mid", "implied_move_ask", "fair_move", "ci_low", "ci_high",
    "edge", "z", "score", "structure", "detail", "entry_side", "entry_price",
    "max_gain", "max_loss", "spread_pct", "spread_cost_pct_of_edge",
    "open_interest", "conf_mult", "n_events", "screened", "screen_reason", "flags",
    "spot", "expiry", "atm_strike", "straddle_bid", "straddle_mid", "straddle_ask",
    "legs_json",
]


def _pct(x, digits=1):
    return "—" if x is None or not np.isfinite(x) else f"{100 * x:.{digits}f}%"


def _dollars(x):
    if x is None or not np.isfinite(x):
        return "—"
    return "unlimited" if np.isinf(x) else f"${x:,.0f}"


def _row_html(r) -> str:
    max_gain = "unlimited" if np.isinf(r.max_gain) else _dollars(r.max_gain)
    fair = f"{_pct(r.fair_move)} <span class=muted>[{_pct(r.ci_low)}–{_pct(r.ci_high)}]</span>"
    implied = f"{_pct(r.implied_move_mid)} <span class=muted>ask {_pct(r.implied_move_ask)}</span>"
    spread_edge = (
        "—" if not np.isfinite(r.spread_cost_pct_of_edge) else f"{r.spread_cost_pct_of_edge:.0f}%"
    )
    detail = f"<div class=muted>{html.escape(str(r.detail))}</div>" if r.detail else ""
    return (
        "<tr>"
        f"<td class=tk><strong>{html.escape(str(r.ticker))}</strong>"
        f"<div class=muted>{html.escape(str(r.name or ''))}</div></td>"
        f"<td>{r.earnings_date} <span class=muted>{html.escape(str(r.session))}</span></td>"
        f"<td class=num>{implied}</td>"
        f"<td class=num>{fair}</td>"
        f"<td class=num>{_pct(r.edge, 0)}</td>"
        f"<td class=num>{r.score:+.2f}</td>"
        f"<td>{html.escape(str(r.structure))}{detail}</td>"
        f"<td class=num>{max_gain} / {_dollars(r.max_loss)}</td>"
        f"<td class=num>{spread_edge}</td>"
        f"<td class=num>{r.conf_mult:.2f}</td>"
        f"<td class=num>{int(r.n_events)}</td>"
        f"<td class=flags>{html.escape(str(r.flags or ''))}</td>"
        "</tr>"
    )


# --------------------------------------------------- plain-English trade plan
SESSION_PHRASE = {
    "BMO": "before the market opens",
    "AMC": "after the close",
    "unknown": "timing unconfirmed",
}


def _fmt_day(d) -> str:
    d = pd.Timestamp(d)
    return d.strftime("%a %b %-d")


def _legs(row) -> list[dict]:
    try:
        return json.loads(row.legs_json) if row.legs_json else []
    except (ValueError, TypeError):
        return []


def order_lines(row) -> list[str]:
    """Broker-ticket lines, e.g. 'SELL 2 x BAC  $47 CALL  exp Fri Jul 17'."""
    exp = _fmt_day(row.expiry)
    return [
        f"{leg['action']} {int(row.contracts)} × {row.ticker}  ${leg['strike']:g} {leg['right']}  exp {exp}"
        for leg in _legs(row)
    ]


def _breakevens(row) -> tuple[float, float] | None:
    legs = _legs(row)
    if not legs:
        return None
    per_share = row.entry_price / 100.0
    calls = [l["strike"] for l in legs if l["right"] == "CALL"]
    puts = [l["strike"] for l in legs if l["right"] == "PUT"]
    if row.structure == "iron fly":
        atm = min(calls)  # short strike
        return atm - per_share, atm + per_share
    if row.structure == "long straddle":
        atm = calls[0]
        return atm - per_share, atm + per_share
    if row.structure == "long strangle":
        return min(puts) - per_share, max(calls) + per_share
    return None


def why_text(row) -> str:
    implied, fair = 100 * row.implied_move_mid, 100 * row.fair_move
    be = _breakevens(row)
    be_txt = f"${be[0]:,.2f} and ${be[1]:,.2f}" if be else "the breakevens"
    n = int(row.n_events)
    if row.entry_side == "credit":
        return (
            f"The options market is pricing a ±{implied:.1f}% earnings move for "
            f"{row.ticker}, but over its recent {n} reports it has typically moved "
            f"about ±{fair:.1f}%. That makes the move look ≈{100 * row.edge:.0f}% "
            f"overpriced, so this trade sells that expensive insurance with wings for "
            f"protection. You collect ${row.entry_price * row.contracts:,.0f} up front "
            f"and keep all of it if {row.ticker} closes between {be_txt} at expiry. "
            f"No matter how wild the move, you cannot lose more than "
            f"${row.position_risk:,.0f}."
        )
    return (
        f"The options market is pricing only a ±{implied:.1f}% earnings move for "
        f"{row.ticker}, but over its recent {n} reports it has typically moved about "
        f"±{fair:.1f}%. The move looks ≈{abs(100 * row.edge):.0f}% underpriced, so "
        f"this trade buys it cheaply. It costs ${-row.cash_flow:,.0f} total — the most "
        f"you can lose — and profits if {row.ticker} is beyond {be_txt} at expiry "
        f"(the bigger the move, the bigger the win)."
    )


def _plan_card(row, ticker_moves: list[float] | None = None) -> str:
    verb = "Sell the move" if row.entry_side == "credit" else "Buy the move"
    money = (
        f"Collect ≈ <strong>${row.cash_flow:,.0f}</strong> credit"
        if row.entry_side == "credit"
        else f"Costs ≈ <strong>${-row.cash_flow:,.0f}</strong>"
    )
    gain = "unlimited" if np.isinf(row.position_max_gain) else f"${row.position_max_gain:,.0f}"
    ticket = "".join(f"<li>{html.escape(t)}</li>" for t in order_lines(row))
    chart = (
        charts.build_chart(row, ticker_moves, f"ch-{row.ticker}") if ticker_moves else ""
    )
    return f"""
<div class=card>
  <div class=cardhead>
    <span class=tkbig>{html.escape(str(row.ticker))}</span>
    <span class=verb>{verb} — {html.escape(str(row.structure))}</span>
  </div>
  <div class=muted>{html.escape(str(row.name or ''))} · reports {_fmt_day(row.earnings_date)}
      {SESSION_PHRASE.get(row.session, '')}</div>
  <div class=when>📅 Place this order on <strong>{_fmt_day(row.entry_by)}</strong>
      (any time before the 4pm ET close)</div>
  <ul class=ticket>{ticket}</ul>
  <div class=money>{money} · max gain {gain} · max loss <strong>${row.position_risk:,.0f}</strong></div>
  {chart}
  <details><summary>Why this trade?</summary><p>{html.escape(why_text(row))}</p></details>
</div>"""


def render_plan_section(
    plan: pd.DataFrame,
    account: float = config.PAPER_ACCOUNT,
    moves: pd.DataFrame | None = None,
) -> str:
    if plan is None or plan.empty:
        return (
            "<h2>Paper trade plan ($10,000 account)</h2>"
            "<p class=muted>No positions today — either nothing has enough edge, "
            "or entry windows have passed. That is the default state, not a bug.</p>"
        )
    risk = plan["position_risk"].sum()
    credit = plan.loc[plan["entry_side"] == "credit", "cash_flow"].sum()
    debit = -plan.loc[plan["entry_side"] == "debit", "cash_flow"].sum()
    tiles = "".join(
        f'<div class=tile><div class=v>{v}</div><div class=k>{k}</div></div>'
        for v, k in [
            (len(plan), "positions to order"),
            (f"${risk:,.0f}", f"total at risk (budget ${account * config.RISK_BUDGET_PCT:,.0f})"),
            (f"${credit:,.0f}", "credit collected"),
            (f"${debit:,.0f}", "debit paid"),
        ]
    )
    moves_by_ticker: dict[str, list[float]] = {}
    if moves is not None and len(moves):
        moves_by_ticker = {
            t: g["move"].astype(float).tolist() for t, g in moves.groupby("ticker")
        }
    cards = "".join(
        _plan_card(r, moves_by_ticker.get(r.ticker)) for r in plan.itertuples(index=False)
    )
    return (
        "<h2>Paper trade plan ($10,000 account)</h2>"
        "<p class=muted>Paper trading only — this is the Q2 forward test, not investment "
        "advice. Prices are yesterday's close; enter with limit orders near the quoted "
        "values and skip any fill that is much worse.</p>"
        f"<div class=tiles>{tiles}</div><div class=cards>{cards}</div>"
    )


HEADERS = (
    "<tr><th>Ticker</th><th>Earnings</th><th>Implied (mid)</th><th>Fair ± CI (80%)</th>"
    "<th>Edge</th><th>Score</th><th>Structure</th><th>Max gain / loss</th>"
    "<th>Spread / edge</th><th>Conf</th><th>n</th><th>Flags</th></tr>"
)

CSS = """
:root { --ink:#1a1d21; --muted:#697077; --line:#e0e3e7; --bg:#ffffff; --card:#f6f7f8;
        /* chart palette — validated (dataviz six checks) against --card surfaces */
        --c1:#2a78d6; --cgood:#0ca30c; --cbad:#d03b3b; --cimp:#4a3aa7; --cfair:#eb6834; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e6e8ea; --muted:#9aa1a9; --line:#33383e; --bg:#17191c; --card:#212429;
          --c1:#3987e5; --cgood:#0ca30c; --cbad:#e66767; --cimp:#9085e9; --cfair:#d95926; }
}
* { box-sizing: border-box; }
body { margin:2rem auto; max-width:1200px; padding:0 1rem; background:var(--bg);
       color:var(--ink); font:14px/1.45 system-ui, -apple-system, sans-serif; }
h1 { font-size:1.3rem; margin-bottom:.2rem; } h2 { font-size:1.05rem; margin-top:2rem; }
.sub { color:var(--muted); margin-top:0; }
.tiles { display:flex; gap:.75rem; flex-wrap:wrap; margin:1.2rem 0; }
.tile { background:var(--card); border:1px solid var(--line); border-radius:8px;
        padding:.7rem 1rem; min-width:9rem; }
.tile .v { font-size:1.45rem; font-weight:650; } .tile .k { color:var(--muted); font-size:.8rem; }
.tablewrap { overflow-x:auto; }
table { border-collapse:collapse; width:100%; }
th { text-align:left; font-size:.75rem; text-transform:uppercase; letter-spacing:.04em;
     color:var(--muted); border-bottom:2px solid var(--line); padding:.45rem .6rem;
     white-space:nowrap; }
td { border-bottom:1px solid var(--line); padding:.5rem .6rem; vertical-align:top; }
td.num { text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }
td.tk { white-space:nowrap; }
.muted { color:var(--muted); font-size:.85em; }
.flags { color:var(--muted); font-size:.8em; max-width:14rem; }
.banner { background:var(--card); border:1px dashed var(--muted); border-radius:8px;
          padding:.6rem 1rem; margin:1rem 0; font-weight:600; }
.cards { display:grid; grid-template-columns:repeat(auto-fill, minmax(320px, 1fr));
         gap:1rem; margin:1rem 0 1.5rem; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px;
        padding:1rem 1.1rem; }
.cardhead { display:flex; align-items:baseline; gap:.6rem; flex-wrap:wrap; }
.tkbig { font-size:1.25rem; font-weight:700; }
.verb { color:var(--muted); font-weight:600; }
.when { margin:.55rem 0 .2rem; }
.ticket { list-style:none; padding:.55rem .7rem; margin:.45rem 0; background:var(--bg);
          border:1px solid var(--line); border-radius:8px;
          font-family:ui-monospace, SFMono-Regular, Menlo, monospace; font-size:.85rem; }
.ticket li { padding:.12rem 0; white-space:nowrap; }
.money { margin:.3rem 0 .5rem; }
details summary { cursor:pointer; color:var(--muted); font-weight:600; margin-top:.2rem; }
details p { margin:.5rem 0 0; }
""" + charts.CHART_CSS


def render_html(
    scored: pd.DataFrame,
    run_date: date,
    banner: str = "",
    plan: pd.DataFrame | None = None,
    moves: pd.DataFrame | None = None,
) -> str:
    live = scored[~scored["screened"]]
    killed = scored[scored["screened"]]
    trades = live[~live["structure"].isin(["no trade", "no affordable structure"])]

    tiles = "".join(
        f'<div class=tile><div class=v>{v}</div><div class=k>{k}</div></div>'
        for v, k in [
            (len(scored), "events scored"),
            (len(live), "pass liquidity screen"),
            (len(killed), "screened out"),
            (len(trades), "actionable structures"),
        ]
    )
    banner_html = f'<div class=banner>{html.escape(banner)}</div>' if banner else ""
    live_rows = "".join(_row_html(r) for r in live.itertuples(index=False))
    killed_rows = "".join(_row_html(r) for r in killed.itertuples(index=False))
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<title>Earnings dashboard — {run_date}</title><style>{CSS}</style></head><body>
<h1>Earnings edge dashboard</h1>
<p class=sub>{run_date} · free-data v1 · paper only · edge = (implied − fair) / fair</p>
{banner_html}
<div class=tiles>{tiles}</div>
{render_plan_section(plan, moves=moves)}
<h2>Ranked (passing liquidity screen)</h2>
<div class=tablewrap><table>{HEADERS}{live_rows or '<tr><td colspan=12>none</td></tr>'}</table></div>
<h2>Screened out (spread &gt; {config.MAX_SPREAD_PCT:.0%} of straddle, OI &lt; {config.MIN_OPEN_INTEREST}, or dead quotes)</h2>
<div class=tablewrap><table>{HEADERS}{killed_rows or '<tr><td colspan=12>none</td></tr>'}</table></div>
<script>{charts.CHART_JS}</script>
</body></html>
"""


def run(
    scored: pd.DataFrame | None = None,
    run_date: date | None = None,
    out_dir=None,
    banner: str = "",
    plan: pd.DataFrame | None = None,
    moves: pd.DataFrame | None = None,
) -> tuple:
    config.ensure_dirs()
    run_date = run_date or date.today()
    out_dir = out_dir or config.DASHBOARD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if scored is None:
        scored = pd.read_parquet(config.SCORED_PARQUET)
    if moves is None and plan is not None and len(plan) and config.MOVES_PARQUET.exists():
        moves = pd.read_parquet(config.MOVES_PARQUET)

    html_path = out_dir / f"daily_{run_date}.html"
    csv_path = out_dir / f"daily_{run_date}.csv"
    html_path.write_text(render_html(scored, run_date, banner=banner, plan=plan, moves=moves))
    cols = [c for c in CSV_COLUMNS if c in scored.columns]
    scored[cols].to_csv(csv_path, index=False)
    if plan is not None and len(plan):
        plan.drop(columns=["legs_json"]).to_csv(
            out_dir / f"daily_{run_date}_plan.csv", index=False
        )
    log.info("dashboard -> %s and %s", html_path, csv_path)
    return html_path, csv_path


if __name__ == "__main__":
    config.setup_logging()
    run()
