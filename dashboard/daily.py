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
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from common import config
from dashboard import charts, reddit_tab, value_tab

log = logging.getLogger("ete.dashboard")


def _memos_for(valuations: pd.DataFrame | None) -> dict[str, str]:
    if valuations is None or not len(valuations):
        return {}
    shown = valuations[
        valuations["verdict"].isin(["buy candidate", "watch (needs price)"])
    ]["ticker"].head(60).tolist()
    return value_tab.load_latest_memos(shown)


def _thesis_fn():
    try:
        from memos.generator import thesis_driver

        return thesis_driver
    except Exception:  # pragma: no cover - defensive
        return None

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


STRUCTURE_EXPLAINER = """
<details class=howto><summary>How to read these trades (plain English)</summary>
<div class=howtogrid>
<div><strong>Iron fly — "sell the move"</strong><br>
You SELL a call and a put at the current price (collecting cash now) and BUY a
cheaper call above and put below as insurance wings. If the stock barely moves
by expiry, every option expires worthless and you keep the cash collected.
If it moves a lot, the wings cap your loss at the stated max. Used when the
options market prices a BIGGER earnings move than this stock historically makes.</div>
<div><strong>Long straddle — "buy the move"</strong><br>
You BUY a call and a put at the current price. A big move in EITHER direction
makes one of them very valuable; a quiet print loses the (capped) cost. Used
when the market prices a SMALLER move than this stock usually makes.</div>
<div><strong>Long strangle — cheaper "buy the move"</strong><br>
Same idea as the straddle but the call is above and the put below the current
price, so it costs less and needs a bigger move to pay.</div>
<div><strong>Reading a ticket</strong><br>
"SELL 2 × BAC $47 CALL exp Fri Jul 17" = sell-to-open two contracts of the
$47-strike call expiring that Friday. Place all legs of a card as ONE order
(a broker "combo"/multi-leg ticket) at a limit near the shown price, on the
date the card says, before the 4pm ET close. Skip any fill much worse than
quoted — the edge is not big enough to pay a bad fill.</div>
</div></details>
"""


def _week_strip(plan: pd.DataFrame) -> str:
    if plan is None or plan.empty:
        return ""
    pills = "".join(
        f'<span class=pill><strong>{_fmt_day(r.entry_by)}</strong> · '
        f'{html.escape(str(r.ticker))} {html.escape(str(r.structure))}</span>'
        for r in plan.sort_values("entry_by").itertuples(index=False)
    )
    return f'<div class=weekstrip><span class=muted>This week:</span> {pills}</div>'


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
        f"{_week_strip(plan)}"
        f"{STRUCTURE_EXPLAINER}"
        f"<div class=tiles>{tiles}</div><div class=cards>{cards}</div>"
    )


HEADERS = (
    "<tr><th>Ticker</th><th>Earnings</th><th>Implied (mid)</th><th>Fair ± CI (80%)</th>"
    "<th>Edge</th><th>Score</th><th>Structure</th><th>Max gain / loss</th>"
    "<th>Spread / edge</th><th>Conf</th><th>n</th><th>Flags</th></tr>"
)


# ------------------------------------------------------- tab 2: squeeze watch
def _meter(value: float, lo: float = 0.0, hi: float = 100.0) -> str:
    if value is None or not np.isfinite(value):
        return '<span class=muted>—</span>'
    pct = max(0.0, min(1.0, (value - lo) / (hi - lo))) * 100
    return (
        f'<span class=meter aria-hidden=true><span class=meterfill '
        f'style="width:{pct:.0f}%"></span></span>'
    )


def _trend_arrow(t: float) -> str:
    if t is None or not np.isfinite(t):
        return "—"
    if t > 0.02:
        return f"▲ +{100 * t:.0f}%"
    if t < -0.02:
        return f"▼ {100 * t:.0f}%"
    return f"≈ {100 * t:+.0f}%"


def squeeze_why(r) -> str:
    dtc = f"{r.days_to_cover:.1f}" if np.isfinite(r.days_to_cover) else "?"
    trend = (
        "and shorts were still adding at the last settlement"
        if np.isfinite(r.si_trend) and r.si_trend > 0.02
        else "though shorts have started covering"
        if np.isfinite(r.si_trend) and r.si_trend < -0.02
        else "with short interest roughly flat"
    )
    turn = f"{100 * r.float_turnover:.0f}%" if np.isfinite(r.float_turnover) else "?"
    return (
        f"{100 * r.si_pct_float:.0f}% of {r.ticker}'s float is sold short and would take "
        f"about {dtc} days of normal volume to buy back, {trend}. {turn} of the float "
        f"already trades hands daily, so forced short covering after a positive surprise "
        f"has to chase a fast-moving stock. This is a lottery ticket, not an edge trade: "
        f"the call can easily expire worthless and lose 100% of its cost — which is why "
        f"it is capped at ${config.SQUEEZE_MAX_COST:.0f} and kept out of the main risk budget."
    )


def _squeeze_card(r) -> str:
    ticket = ""
    money = ""
    if r.structure == "long call":
        ticket = (
            f'<ul class=ticket><li>BUY 1 × {html.escape(str(r.ticker))}  '
            f"${r.strike:g} CALL  exp {_fmt_day(r.expiry)}</li></ul>"
        )
        money = (
            f"<div class=money>Costs ≈ <strong>${r.entry_price:,.0f}</strong> "
            f"(the max loss) · max gain unlimited</div>"
        )
    elif r.structure == "no affordable call":
        money = '<div class=money>No listed call fits the $250 budget.</div>'
    if r.structure == "long call":
        when = (
            f"📅 Place this order on <strong>{_fmt_day(r.entry_by)}</strong> "
            f"(any time before the 4pm ET close)"
        )
    else:
        when = (
            f"⏳ Options not priced yet (reports beyond the 10-trading-day chain window) — "
            f"entry window closes <strong>{_fmt_day(r.entry_by)}</strong>"
            if r.structure == "watch only"
            else f"Entry window closes <strong>{_fmt_day(r.entry_by)}</strong>"
        )
    src = {"nasdaq": "official Nasdaq settlement", "yahoo": "Yahoo estimate", "none": "no data"}
    return f"""
<div class=card>
  <div class=cardhead><span class=tkbig>{html.escape(str(r.ticker))}</span>
    <span class=verb>squeeze score {r.squeeze_score:.0f}/100</span></div>
  <div class=muted>{html.escape(str(r.name or ''))} · reports {_fmt_day(r.earnings_date)}
      {SESSION_PHRASE.get(r.session, '')}</div>
  <div class=srow>Short interest: <strong>{100 * r.si_pct_float:.1f}% of float</strong>
      <span class=muted>({src.get(r.si_source, r.si_source)})</span> {_meter(100 * r.si_pct_float, 0, 30)}</div>
  <div class=srow>Days to cover: <strong>{r.days_to_cover:.1f}</strong>
      · SI trend: {_trend_arrow(r.si_trend)}
      · float turnover: <strong>{100 * r.float_turnover:.1f}%/day</strong></div>
  <div class=when>{when}</div>
  {ticket}{money}
  <details><summary>Why this trade?</summary><p>{html.escape(squeeze_why(r))}</p></details>
</div>"""


def render_squeeze_section(squeeze: pd.DataFrame | None) -> str:
    intro = (
        "<h2>Squeeze watch — crowded shorts into earnings</h2>"
        "<p class=muted>Names whose short positioning makes the upside tail fat: heavily "
        "shorted, slow to cover, fast-moving float. Long calls only, ≤ $250 each, outside "
        "the main risk budget. These same names are barred from premium-selling on the "
        "Trade plan tab — squeeze setups are how iron-fly sellers get hurt.</p>"
    )
    if squeeze is None or squeeze.empty:
        return intro + "<p class=muted>No positioning data yet — run the pipeline.</p>"
    cands = squeeze[squeeze["candidate"]]
    cards = "".join(_squeeze_card(r) for r in cands.itertuples(index=False)) or (
        "<p class=muted>No candidates today — nothing crosses the "
        f"{config.SQUEEZE_MIN_SI:.0%}-of-float / score-{config.SQUEEZE_SCORE_MIN:.0f} bar. "
        "That is the default state.</p>"
    )
    rows = "".join(
        f"<tr><td class=tk><strong>{html.escape(str(r.ticker))}</strong></td>"
        f"<td data-v={r.squeeze_score:.1f} class=num>{r.squeeze_score:.0f} {_meter(r.squeeze_score)}</td>"
        f"<td data-v={_sv(100 * r.si_pct_float)} class=num>{_pct(r.si_pct_float)}</td>"
        f"<td data-v={_sv(r.days_to_cover)} class=num>{r.days_to_cover:.1f}</td>"
        f"<td data-v={_sv(100 * r.float_turnover)} class=num>{_pct(r.float_turnover)}</td>"
        f"<td data-v={_sv(100 * r.si_trend)} class=num>{_trend_arrow(r.si_trend)}</td>"
        f"<td>{r.earnings_date} <span class=muted>{html.escape(str(r.session))}</span></td>"
        f"<td>{html.escape(str(r.structure))}</td></tr>"
        for r in squeeze.head(25).itertuples(index=False)
    )
    table = (
        '<h3>Watch list (top 25 by score)</h3><div class=tablewrap><table class=sortable>'
        "<tr><th>Ticker</th><th data-s=1>Score</th><th data-s=1>SI % float</th>"
        "<th data-s=1>Days to cover</th><th data-s=1>Float turnover</th><th data-s=1>SI trend</th>"
        "<th>Earnings</th><th>Structure</th></tr>"
        f"{rows}</table></div>"
    )
    return intro + f"<div class=cards>{cards}</div>" + table


# ------------------------------------------------------- tab 3: positioning
def _sv(v) -> str:
    return f"{v:.2f}" if v is not None and np.isfinite(v) else "-999"


def render_positioning_section(squeeze: pd.DataFrame | None) -> str:
    positioning = squeeze  # the squeeze frame carries events + positioning + score
    intro = (
        "<h2>Positioning — Main St vs Wall St, and how fast each name can move</h2>"
        "<p class=muted>Ownership split (institutional vs the retail remainder — a proxy; "
        "true retail flow isn't published free), short crowding, and float velocity "
        "(average daily volume as a share of the float). Click a column header to sort.</p>"
    )
    if positioning is None or positioning.empty:
        return intro + "<p class=muted>No positioning data yet — run the pipeline.</p>"
    df = positioning.sort_values("squeeze_score", ascending=False)
    rows = "".join(
        f"<tr><td class=tk><strong>{html.escape(str(r.ticker))}</strong>"
        f"<div class=muted>{html.escape(str(r.name or ''))}</div></td>"
        f"<td>{r.earnings_date} <span class=muted>{html.escape(str(r.session))}</span></td>"
        f"<td data-v={_sv(r.float_shares / 1e6 if np.isfinite(r.float_shares) else None)} class=num>"
        f"{r.float_shares / 1e6:,.0f}M</td>"
        f"<td data-v={_sv(100 * r.float_turnover)} class=num>{_pct(r.float_turnover)} {_meter(100 * r.float_turnover, 0, 5)}</td>"
        f"<td data-v={_sv(100 * r.inst_pct)} class=num>{_pct(r.inst_pct, 0)} {_meter(100 * r.inst_pct)}</td>"
        f"<td data-v={_sv(100 * r.retail_pct)} class=num>{_pct(r.retail_pct, 0)} {_meter(100 * r.retail_pct)}</td>"
        f"<td data-v={_sv(100 * r.si_pct_float)} class=num>{_pct(r.si_pct_float)} {_meter(100 * r.si_pct_float, 0, 30)}</td>"
        f"<td data-v={_sv(r.days_to_cover)} class=num>{r.days_to_cover:.1f}</td>"
        f"<td data-v={_sv(100 * r.si_trend)} class=num>{_trend_arrow(r.si_trend)}</td>"
        f"<td data-v={r.squeeze_score:.1f} class=num><strong>{r.squeeze_score:.0f}</strong> {_meter(r.squeeze_score)}</td>"
        "</tr>"
        for r in df.itertuples(index=False)
        if np.isfinite(r.float_shares)
    )
    return intro + (
        '<div class=tablewrap><table class=sortable>'
        "<tr><th>Ticker</th><th>Earnings</th><th data-s=1>Float</th>"
        "<th data-s=1>Vol / float (day)</th><th data-s=1>Wall St %</th><th data-s=1>Main St %</th>"
        "<th data-s=1>Short % float</th><th data-s=1>Days to cover</th><th data-s=1>SI trend</th>"
        "<th data-s=1>Squeeze score</th></tr>"
        f"{rows}</table></div>"
    )


TABS_JS = """
document.querySelectorAll('.tabbar button').forEach(function (btn) {
  btn.addEventListener('click', function () {
    document.querySelectorAll('.tabbar button').forEach(function (b) {
      b.classList.toggle('active', b === btn);
      b.setAttribute('aria-selected', b === btn ? 'true' : 'false');
    });
    document.querySelectorAll('.tabpane').forEach(function (p) {
      p.hidden = p.id !== btn.dataset.tab;
    });
    if (history.replaceState) history.replaceState(null, '', '#' + btn.dataset.tab);
  });
});
if (location.hash) {
  var target = document.querySelector('.tabbar button[data-tab="' + location.hash.slice(1) + '"]');
  if (target) target.click();
}
(function () {
  var overlay = document.querySelector('.memo-overlay');
  if (!overlay) return;
  var body = overlay.querySelector('.memo-body');
  function close() { overlay.hidden = true; body.textContent = ''; }
  document.querySelectorAll('.memobtn').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var tpl = document.getElementById(btn.dataset.memo);
      if (!tpl) return;
      body.textContent = '';
      body.appendChild(tpl.content.cloneNode(true));
      overlay.hidden = false;
      overlay.querySelector('.memo-close').focus();
    });
  });
  overlay.querySelector('.memo-close').addEventListener('click', close);
  overlay.addEventListener('click', function (ev) { if (ev.target === overlay) close(); });
  document.addEventListener('keydown', function (ev) {
    if (ev.key === 'Escape' && !overlay.hidden) close();
  });
})();
document.querySelectorAll('table.sortable th[data-s]').forEach(function (th) {
  th.addEventListener('click', function () {
    var table = th.closest('table');
    var idx = Array.prototype.indexOf.call(th.parentNode.children, th);
    var rows = Array.prototype.slice.call(table.querySelectorAll('tr')).slice(1);
    var dir = th.dataset.dir === 'desc' ? 1 : -1;
    th.dataset.dir = dir === 1 ? 'asc' : 'desc';
    rows.sort(function (a, b) {
      var av = parseFloat(a.children[idx].dataset.v || 'NaN');
      var bv = parseFloat(b.children[idx].dataset.v || 'NaN');
      if (isNaN(av) && isNaN(bv)) return 0;
      if (isNaN(av)) return 1;
      if (isNaN(bv)) return -1;
      return dir * (av - bv);
    });
    rows.forEach(function (r) { table.appendChild(r); });
  });
});
"""

CSS = """
:root { --ink:#1a1d21; --muted:#697077; --line:#e0e3e7; --bg:#ffffff; --card:#f6f7f8;
        /* chart palette — validated (dataviz six checks) against --card surfaces */
        --c1:#2a78d6; --cgood:#0ca30c; --cbad:#d03b3b; --cimp:#4a3aa7; --cfair:#eb6834;
        --c1track:#cde2fb; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e6e8ea; --muted:#9aa1a9; --line:#33383e; --bg:#17191c; --card:#212429;
          --c1:#3987e5; --cgood:#0ca30c; --cbad:#e66767; --cimp:#9085e9; --cfair:#d95926;
          --c1track:#0d366b; }
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
.tabbar { display:flex; gap:.4rem; margin:1.1rem 0 1.3rem; border-bottom:2px solid var(--line);
          position:sticky; top:0; background:var(--bg); z-index:10;
          overflow-x:auto; -webkit-overflow-scrolling:touch; scrollbar-width:none; }
.tabbar::-webkit-scrollbar { display:none; }
.tabbar button { background:none; border:none; border-bottom:3px solid transparent;
                 margin-bottom:-2px; padding:.55rem .9rem; font:inherit; font-weight:600;
                 color:var(--muted); cursor:pointer; white-space:nowrap; flex-shrink:0; }
.tabbar button.active { color:var(--ink); border-bottom-color:var(--c1); }
.tabbar button:hover { color:var(--ink); }
.weekstrip { display:flex; gap:.45rem; flex-wrap:wrap; align-items:center; margin:.7rem 0; }
.pill { background:var(--card); border:1px solid var(--line); border-radius:999px;
        padding:.25rem .7rem; font-size:.8rem; white-space:nowrap; }
.howto { background:var(--card); border:1px solid var(--line); border-radius:10px;
         padding:.6rem 1rem; margin:.8rem 0 1rem; }
.howto summary { margin:0; }
.howtogrid { display:grid; grid-template-columns:repeat(auto-fit, minmax(260px, 1fr));
             gap:.9rem 1.2rem; margin-top:.7rem; font-size:.86rem; line-height:1.5; }
tr:hover td { background:color-mix(in srgb, var(--card) 60%, transparent); }
@media (max-width: 720px) {
  body { margin:.8rem auto; padding:0 .6rem; font-size:13px; }
  h1 { font-size:1.1rem; } h2 { font-size:.95rem; }
  th, td { padding:.35rem .4rem; }
  .tile { min-width:7rem; padding:.5rem .7rem; }
  .tile .v { font-size:1.15rem; }
  .cards { grid-template-columns:1fr; }
  .ticket { font-size:.78rem; }
  .flags { max-width:9rem; }
  .memo-dialog { padding:.9rem .9rem 1.4rem; }
  .memo-overlay { padding:1.5vh .4rem; }
}
.meter { display:inline-block; width:56px; height:8px; border-radius:4px;
         background:var(--c1track); vertical-align:middle; margin-left:.4rem; }
.meterfill { display:block; height:100%; border-radius:4px; background:var(--c1); }
.srow { margin:.3rem 0; }
table.sortable th[data-s] { cursor:pointer; text-decoration:underline dotted; }
.memobtn { background:none; border:none; padding:0; font:inherit; font-weight:700;
           color:var(--c1); cursor:pointer; text-decoration:underline dotted; }
.memo-overlay { position:fixed; inset:0; background:rgba(0,0,0,.45); z-index:20;
                display:flex; align-items:flex-start; justify-content:center;
                padding:3vh 1rem; overflow-y:auto; }
.memo-overlay[hidden] { display:none; }
.memo-dialog { background:var(--bg); color:var(--ink); border:1px solid var(--line);
               border-radius:12px; max-width:820px; width:100%; padding:1.2rem 1.6rem 2rem;
               box-shadow:0 12px 40px rgba(0,0,0,.35); }
.memo-close { float:right; background:var(--card); border:1px solid var(--line);
              border-radius:6px; padding:.3rem .7rem; font:inherit; color:var(--muted);
              cursor:pointer; }
.memo-body h2 { font-size:1.2rem; margin-top:.4rem; }
.memo-body h3 { font-size:1rem; margin-top:1.2rem; }
.memo-body table { border-collapse:collapse; margin:.5rem 0; }
.memo-body td, .memo-body th { border-bottom:1px solid var(--line); padding:.3rem .6rem;
                               text-align:left; }
.memo-body blockquote { border-left:3px solid var(--line); margin:.6rem 0;
                        padding:.2rem .8rem; color:var(--muted); }
.memo-body p, .memo-body li { line-height:1.5; }
""" + charts.CHART_CSS


def render_html(
    scored: pd.DataFrame,
    run_date: date,
    banner: str = "",
    plan: pd.DataFrame | None = None,
    moves: pd.DataFrame | None = None,
    squeeze: pd.DataFrame | None = None,
    valuations: pd.DataFrame | None = None,
    events: pd.DataFrame | None = None,
    insiders: pd.DataFrame | None = None,
    gurus: pd.DataFrame | None = None,
    ideas: pd.DataFrame | None = None,
    growth_gates: pd.DataFrame | None = None,
    theme_summary: pd.DataFrame | None = None,
    growth_memos: dict[str, str] | None = None,
    autopsy_summary: str = "",
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
    n_cand = int(squeeze["candidate"].sum()) if squeeze is not None and len(squeeze) else 0
    n_buy = (
        int((valuations["verdict"] == "buy candidate").sum())
        if valuations is not None and len(valuations) else 0
    )
    n_ideas = len(ideas) if ideas is not None else 0
    reddit_html = reddit_tab.render_reddit_tab(
        ideas, growth_gates, theme_summary,
        memos_by_ticker=growth_memos, autopsy_summary=autopsy_summary,
    )
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html>
<html lang=en><head><meta charset=utf-8>
<meta name=viewport content="width=device-width, initial-scale=1">
<link rel=icon href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📈</text></svg>">
<title>Earnings dashboard — {run_date}</title><style>{CSS}</style></head><body>
<h1>Earnings edge dashboard</h1>
<p class=sub>{run_date} · free-data v1 · paper only · edge = (implied − fair) / fair
 · <span title="when this page was generated">updated {stamp}</span></p>
{banner_html}
<div class=tabbar role=tablist>
  <button class=active role=tab aria-selected=true data-tab=plan>Trade plan</button>
  <button role=tab aria-selected=false data-tab=squeeze>Squeeze watch{f' ({n_cand})' if n_cand else ''}</button>
  <button role=tab aria-selected=false data-tab=positioning>Positioning</button>
  <button role=tab aria-selected=false data-tab=value>Value screen{f' ({n_buy})' if n_buy else ''}</button>
  <button role=tab aria-selected=false data-tab=valuesoon>Reporting soon</button>
  <button role=tab aria-selected=false data-tab=reddit>Reddit Suggestions{f' ({n_ideas})' if n_ideas else ''}</button>
</div>
<section class=tabpane id=plan>
<div class=tiles>{tiles}</div>
{render_plan_section(plan, moves=moves)}
<h2>Ranked (passing liquidity screen)</h2>
<div class=tablewrap><table>{HEADERS}{live_rows or '<tr><td colspan=12>none</td></tr>'}</table></div>
<h2>Screened out (spread &gt; {config.MAX_SPREAD_PCT:.0%} of straddle, OI &lt; {config.MIN_OPEN_INTEREST}, or dead quotes)</h2>
<div class=tablewrap><table>{HEADERS}{killed_rows or '<tr><td colspan=12>none</td></tr>'}</table></div>
</section>
<section class=tabpane id=squeeze hidden>
{render_squeeze_section(squeeze)}
</section>
<section class=tabpane id=positioning hidden>
{render_positioning_section(squeeze)}
</section>
<section class=tabpane id=value hidden>
{value_tab.render_value_screen(valuations, insiders=insiders, gurus=gurus,
                               memos_by_ticker=_memos_for(valuations))}
</section>
<section class=tabpane id=valuesoon hidden>
{value_tab.render_reporting_soon(valuations, events, today=run_date, thesis_fn=_thesis_fn())}
</section>
<section class=tabpane id=reddit hidden>
{reddit_html}
</section>
<div class="memo-overlay" hidden><div class="memo-dialog" role="dialog" aria-modal="true">
<button class="memo-close" aria-label="Close">✕ close</button>
<div class="memo-body"></div></div></div>
<script>{charts.CHART_JS}</script>
<script>{TABS_JS}</script>
</body></html>
"""


def run(
    scored: pd.DataFrame | None = None,
    run_date: date | None = None,
    out_dir=None,
    banner: str = "",
    plan: pd.DataFrame | None = None,
    moves: pd.DataFrame | None = None,
    squeeze: pd.DataFrame | None = None,
) -> tuple:
    config.ensure_dirs()
    run_date = run_date or date.today()
    out_dir = out_dir or config.DASHBOARD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if scored is None:
        scored = pd.read_parquet(config.SCORED_PARQUET)
    if plan is None and len(scored):
        # regenerating without an explicit plan (e.g. the weekly run) must
        # not silently drop the trade-plan cards — rebuild from scored
        from scoring.size import build_trade_plan

        plan = build_trade_plan(scored, today=run_date or date.today())
    if moves is None and plan is not None and len(plan) and config.MOVES_PARQUET.exists():
        moves = pd.read_parquet(config.MOVES_PARQUET)
    if squeeze is None and config.SQUEEZE_PARQUET.exists():
        squeeze = pd.read_parquet(config.SQUEEZE_PARQUET)

    def _opt(path):
        return pd.read_parquet(path) if path.exists() else None

    valuations = _opt(config.VALUATIONS_PARQUET)
    events = _opt(config.EVENTS_PARQUET)
    v_insiders = _opt(config.INSIDERS_PARQUET)
    v_gurus = _opt(config.GURUS_PARQUET)
    ideas = _opt(config.DATA_DIR / "growth_ideas.parquet")
    growth_gates = _opt(config.DATA_DIR / "growth_gates.parquet")
    mentions = _opt(config.DATA_DIR / "mentions_latest.parquet")
    theme_summary = None
    if mentions is not None and len(mentions):
        from themes.cluster import theme_mention_summary

        theme_summary = theme_mention_summary(mentions)
    growth_memos = {}
    if ideas is not None and len(ideas):
        raw = value_tab.load_latest_memos([f"{t}_growth" for t in ideas["ticker"]])
        growth_memos = {k.replace("_growth", ""): v for k, v in raw.items()}
    autopsy_summary = ""
    autopsy_path = config.REPO_ROOT / "reports" / "cohort_autopsy.md"
    if autopsy_path.exists():
        import re as _re

        m = _re.search(
            r"wsb_2026_index.*?Total return since publication: ([\d.\-]+%).*?SPY: ([\d.\-]+%)",
            autopsy_path.read_text(), _re.S,
        )
        if m:
            autopsy_summary = (
                f"2026 index +{m.group(1).lstrip('+')} vs SPY {m.group(2)} — but beta ~2, "
                "two names carried everything; scout, not signal."
            )

    html_path = out_dir / f"daily_{run_date}.html"
    csv_path = out_dir / f"daily_{run_date}.csv"
    html_path.write_text(
        render_html(
            scored, run_date, banner=banner, plan=plan, moves=moves, squeeze=squeeze,
            valuations=valuations, events=events, insiders=v_insiders, gurus=v_gurus,
            ideas=ideas, growth_gates=growth_gates, theme_summary=theme_summary,
            growth_memos=growth_memos, autopsy_summary=autopsy_summary,
        )
    )
    if ideas is not None and len(ideas):
        ideas.to_csv(out_dir / f"reddit_ideas_{run_date}.csv", index=False)
    if valuations is not None and len(valuations):
        valuations.to_csv(out_dir / f"value_screen_{run_date}.csv", index=False)
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
