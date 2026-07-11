"""Interactive per-trade risk/value charts (inline SVG + vanilla JS).

For each planned position, two vertically aligned panels share one x-axis
(the % earnings move):

  * payoff at expiry ($ for the whole position) — 2px line, profit region
    washed in the series hue, zero hairline baseline;
  * histogram of THIS name's actual past earnings moves, each move classified
    by whether this exact structure would have won or lost (status colors,
    with legend + table view so color never carries meaning alone).

Reference markers show the move the market is pricing (±implied) and the
model's fair move (±fair). A crosshair + tooltip (pointer and keyboard)
reads out price, P&L, and historical frequency at any move size. No dual
axes anywhere — the panels are separate charts sharing an x-domain.

All colors live in CSS custom properties (light/dark validated against the
card surfaces with the dataviz palette validator).
"""

from __future__ import annotations

import html
import json
import math

# geometry (viewBox units; svg scales responsively)
W = 640
ML, MR = 56, 14
PAY_H, PAY_PAD = 118, 10
HIST_H = 132
AXIS_H = 24
GAP_H = 8
TOTAL_H = PAY_H + GAP_H + HIST_H + AXIS_H
PLOT_W = W - ML - MR


# ------------------------------------------------------------------ payoff --
def leg_value(leg: dict, price: float) -> float:
    if leg["right"] == "CALL":
        return max(0.0, price - leg["strike"])
    return max(0.0, leg["strike"] - price)


def payoff_at(move_pct: float, row) -> float:
    """Position P&L at expiry if the stock moves `move_pct` from spot."""
    price = row.spot * (1.0 + move_pct)
    legs = json.loads(row.legs_json)
    intrinsic = sum(
        (1 if l["action"] == "BUY" else -1) * leg_value(l, price) for l in legs
    )
    return row.cash_flow + row.contracts * 100.0 * intrinsic


def chart_domain(row, moves_pct: list[float]) -> float:
    """Symmetric half-width of the x-domain, snapped to a clean %."""
    strikes = [l["strike"] for l in json.loads(row.legs_json)]
    strike_reach = max(abs(k / row.spot - 1.0) for k in strikes)
    reach = max(
        1.4 * row.implied_move_mid,
        1.15 * max((abs(m) for m in moves_pct), default=0.0),
        1.3 * strike_reach,
        0.04,
    )
    step = 0.01 if reach <= 0.12 else 0.02 if reach <= 0.30 else 0.05
    return min(math.ceil(reach / step) * step, 0.60)


def payoff_knots(row, half: float) -> list[tuple[float, float]]:
    """Piecewise-linear payoff sampled at strikes + domain edges."""
    xs = {-half, half}
    for leg in json.loads(row.legs_json):
        m = leg["strike"] / row.spot - 1.0
        if -half < m < half:
            xs.add(m)
    return [(x, payoff_at(x, row)) for x in sorted(xs)]


def breakeven_moves(knots: list[tuple[float, float]]) -> list[float]:
    """x positions where the piecewise payoff crosses zero."""
    out = []
    for (x0, y0), (x1, y1) in zip(knots, knots[1:]):
        if y0 == 0:
            out.append(x0)
        if (y0 < 0 < y1) or (y1 < 0 < y0):
            out.append(x0 + (0 - y0) * (x1 - x0) / (y1 - y0))
    return out


# --------------------------------------------------------------- histogram --
def bin_moves(moves_pct: list[float], row, half: float, target_bins: int = 18) -> list[dict]:
    """Fixed-width bins; each historical move classified win/loss exactly."""
    raw = 2 * half / target_bins
    step = min(
        (s for s in (0.005, 0.01, 0.02, 0.05, 0.10) if s >= raw * 0.75),
        default=0.10,
    )
    n = max(2, math.ceil(2 * half / step))
    lo = -step * n / 2
    bins = [
        {"lo": lo + i * step, "hi": lo + (i + 1) * step, "win": 0, "loss": 0}
        for i in range(n)
    ]
    for m in moves_pct:
        i = min(n - 1, max(0, int((m - lo) / step)))
        key = "win" if payoff_at(m, row) > 0 else "loss"
        bins[i][key] += 1
    return bins


def win_stats(moves_pct: list[float], row) -> tuple[int, int]:
    wins = sum(1 for m in moves_pct if payoff_at(m, row) > 0)
    return wins, len(moves_pct)


# ------------------------------------------------------------------ render --
def _x(move: float, half: float) -> float:
    return ML + (move + half) / (2 * half) * PLOT_W


def _nice_dollar(v: float) -> str:
    return f"-${abs(v):,.0f}" if v < 0 else f"${v:,.0f}"


def _pct_ticks(half: float) -> list[float]:
    for step in (0.02, 0.05, 0.10, 0.20):
        if half / step <= 4:
            break
    k = int(half / step)
    return [i * step for i in range(-k, k + 1)]


def build_chart(row, moves_pct: list[float], chart_id: str) -> str:
    """Full chart block: legend, two SVG panels, tooltip host, table view."""
    half = chart_domain(row, moves_pct)
    knots = payoff_knots(row, half)
    bes = breakeven_moves(knots)
    bins = bin_moves(moves_pct, row, half)
    wins, total = win_stats(moves_pct, row)
    max_count = max((b["win"] + b["loss"] for b in bins), default=1) or 1

    pay_vals = [y for _, y in knots]
    y_hi = max(max(pay_vals), 0) or 1
    y_lo = min(min(pay_vals), 0)
    y_span = (y_hi - y_lo) or 1.0

    def py(v: float) -> float:  # payoff panel y
        return PAY_PAD + (y_hi - v) / y_span * (PAY_H - 2 * PAY_PAD)

    hist_top = PAY_H + GAP_H
    def hy(count: float) -> float:  # histogram panel y (baseline at bottom)
        return hist_top + HIST_H - count / max_count * (HIST_H - 14)

    zero_y = py(0.0)

    # payoff line + profit wash
    line = " ".join(f"{_x(x, half):.1f},{py(v):.1f}" for x, v in knots)
    wash_parts = []
    seq = sorted(set(bes + [k[0] for k in knots]))
    for x0, x1 in zip(seq, seq[1:]):
        mid = (x0 + x1) / 2
        if payoff_at(mid, row) > 0:
            xs0, xs1 = _x(x0, half), _x(x1, half)
            v0, v1 = payoff_at(x0, row), payoff_at(x1, row)
            wash_parts.append(
                f"M{xs0:.1f},{zero_y:.1f} L{xs0:.1f},{py(v0):.1f} "
                f"L{xs1:.1f},{py(v1):.1f} L{xs1:.1f},{zero_y:.1f} Z"
            )
    wash = f'<path d="{" ".join(wash_parts)}" class="c-wash"/>' if wash_parts else ""

    # histogram bars (win bottom, loss stacked above, 2px surface gaps)
    band = PLOT_W / len(bins)
    bar_w = min(band - 4, 24)
    bars = []
    base_y = hist_top + HIST_H
    for b in bins:
        cx = _x((b["lo"] + b["hi"]) / 2, half)
        x0 = cx - bar_w / 2
        if b["win"]:
            top = hy(b["win"])
            bars.append(
                f'<rect x="{x0:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                f'height="{base_y - top:.1f}" rx="3" class="c-win"/>'
            )
        if b["loss"]:
            btm = hy(b["win"]) - (2 if b["win"] else 0)
            top = btm - (hy(0) - hy(b["loss"]))
            h = max(btm - top, 1.5)
            bars.append(
                f'<rect x="{x0:.1f}" y="{top:.1f}" width="{bar_w:.1f}" '
                f'height="{h:.1f}" rx="3" class="c-loss"/>'
            )

    # reference verticals: ±implied (market), ±fair (model) across both panels
    refs, ref_labels = [], []
    for sign in (-1, 1):
        for cls, mv in (("c-imp", row.implied_move_mid), ("c-fair", row.fair_move)):
            m = sign * mv
            if abs(m) < half:
                xr = _x(m, half)
                refs.append(
                    f'<line x1="{xr:.1f}" y1="4" x2="{xr:.1f}" y2="{base_y}" class="{cls} c-ref"/>'
                )
    ref_labels.append(
        f'<text x="{ML + 4}" y="{PAY_PAD + 2}" class="c-lab">'
        f'<tspan class="c-keyimp">▮</tspan> market ±{100 * row.implied_move_mid:.1f}%'
        f'  <tspan class="c-keyfair">▮</tspan> model ±{100 * row.fair_move:.1f}%</text>'
    )

    # axes + ticks
    ticks = []
    for t in _pct_ticks(half):
        xt = _x(t, half)
        ticks.append(
            f'<line x1="{xt:.1f}" y1="{base_y}" x2="{xt:.1f}" y2="{base_y + 4}" class="c-axis"/>'
            f'<text x="{xt:.1f}" y="{base_y + 16}" text-anchor="middle" class="c-tick">'
            f"{'+' if t > 0 else ''}{round(100 * t)}%</text>"
        )
    y_ticks = "".join(
        f'<text x="{ML - 6}" y="{py(v) + 3:.1f}" text-anchor="end" class="c-tick">{_nice_dollar(v)}</text>'
        f'<line x1="{ML}" y1="{py(v):.1f}" x2="{W - MR}" y2="{py(v):.1f}" class="c-grid"/>'
        for v in (y_hi, 0.0, y_lo) if abs(v) > 1e-9 or v == 0.0
    )

    payload = {
        "half": half, "spot": row.spot, "contracts": int(row.contracts),
        "knots": [[round(x, 5), round(v, 2)] for x, v in knots],
        "bins": [[round(b["lo"], 5), round(b["hi"], 5), b["win"], b["loss"]] for b in bins],
        "total": total,
    }

    table_rows = "".join(
        f"<tr><td>{100 * b['lo']:+.1f}% to {100 * b['hi']:+.1f}%</td>"
        f"<td>{b['win']}</td><td>{b['loss']}</td>"
        f"<td>{_nice_dollar(payoff_at((b['lo'] + b['hi']) / 2, row))}</td></tr>"
        for b in bins if b["win"] or b["loss"]
    )
    be_txt = " and ".join(f"{100 * b:+.1f}%" for b in sorted(bes)) or "—"

    return f"""
<div class="chart" id="{chart_id}">
  <div class="chart-title">If {html.escape(str(row.ticker))} moves … you make/lose
    <span class="muted">(win rate on its last {total} reports: <strong>{wins}/{total}</strong>)</span></div>
  <div class="chart-legend">
    <span><span class="key k-line"></span>P&amp;L at expiry</span>
    <span><span class="key k-win"></span>past move → win</span>
    <span><span class="key k-loss"></span>past move → loss</span>
    <span><span class="key k-imp"></span>market-priced move</span>
    <span><span class="key k-fair"></span>model fair move</span>
  </div>
  <svg viewBox="0 0 {W} {TOTAL_H}" width="100%" tabindex="0" role="img"
       aria-label="Payoff and historical earnings-move histogram for {html.escape(str(row.ticker))}">
    {y_ticks}
    <line x1="{ML}" y1="{zero_y:.1f}" x2="{W - MR}" y2="{zero_y:.1f}" class="c-zero"/>
    {wash}
    {"".join(refs)}
    <polyline points="{line}" class="c-pay"/>
    {"".join(ref_labels)}
    {"".join(bars)}
    <line x1="{ML}" y1="{base_y}" x2="{W - MR}" y2="{base_y}" class="c-axis"/>
    {"".join(ticks)}
    <line class="c-cross" x1="0" y1="4" x2="0" y2="{base_y}" visibility="hidden"/>
    <rect class="c-hit" x="{ML}" y="0" width="{PLOT_W}" height="{base_y}" fill="transparent"/>
  </svg>
  <div class="chart-tip" hidden></div>
  <script type="application/json" class="chart-data">{json.dumps(payload)}</script>
  <details class="chart-table"><summary>Table view</summary>
    <p class="muted">Breakevens at {be_txt}. Win rate {wins}/{total} past reports.</p>
    <table><tr><th>Move range</th><th>Wins</th><th>Losses</th><th>P&amp;L at mid</th></tr>{table_rows}</table>
  </details>
</div>"""


CHART_CSS = """
.chart { margin:.6rem 0 .2rem; }
.chart svg { display:block; }
.chart svg:focus { outline:2px solid var(--c1); outline-offset:2px; }
.chart-title { font-weight:600; margin-bottom:.15rem; }
.chart-legend { display:flex; flex-wrap:wrap; gap:.35rem .9rem; color:var(--muted);
                font-size:.78rem; margin:.25rem 0 .3rem; }
.key { display:inline-block; width:14px; height:3px; border-radius:2px;
       vertical-align:middle; margin-right:.35rem; }
.k-line { background:var(--c1); }
.k-win { background:var(--cgood); height:9px; border-radius:3px; }
.k-loss { background:var(--cbad); height:9px; border-radius:3px; }
.k-imp { background:var(--cimp); }
.k-fair { background:var(--cfair); }
.c-pay { fill:none; stroke:var(--c1); stroke-width:2; stroke-linejoin:round; stroke-linecap:round; }
.c-wash { fill:var(--c1); opacity:.10; }
.c-win { fill:var(--cgood); }
.c-loss { fill:var(--cbad); }
.c-ref { stroke-width:1; opacity:.75; }
.c-imp { stroke:var(--cimp); }
.c-fair { stroke:var(--cfair); }
.c-zero, .c-axis { stroke:var(--line); stroke-width:1; }
.c-grid { stroke:var(--line); stroke-width:.5; opacity:.6; }
.c-tick { fill:var(--muted); font-size:10px; font-family:system-ui, sans-serif; }
.c-lab { fill:var(--muted); font-size:10.5px; font-family:system-ui, sans-serif; }
.c-keyimp { fill:var(--cimp); }
.c-keyfair { fill:var(--cfair); }
.c-cross { stroke:var(--ink); stroke-width:1; opacity:.5; }
.chart-tip { position:absolute; pointer-events:none; background:var(--bg);
             border:1px solid var(--line); border-radius:6px; padding:.4rem .6rem;
             font-size:.78rem; box-shadow:0 2px 8px rgba(0,0,0,.12); z-index:5;
             max-width:230px; }
.chart-tip .v { font-weight:700; font-size:.9rem; }
.chart-table table { font-size:.78rem; margin-top:.3rem; }
.chart-table td, .chart-table th { padding:.2rem .5rem; }
.card { position:relative; }
"""

CHART_JS = """
(function () {
  function fmtUsd(v) {
    var s = Math.abs(v).toLocaleString('en-US', {maximumFractionDigits: 0});
    return (v < 0 ? '-$' : '$') + s;
  }
  function payoffAt(knots, x) {
    if (x <= knots[0][0]) return knots[0][1];
    for (var i = 1; i < knots.length; i++) {
      if (x <= knots[i][0]) {
        var a = knots[i-1], b = knots[i], t = (x - a[0]) / (b[0] - a[0] || 1);
        return a[1] + t * (b[1] - a[1]);
      }
    }
    return knots[knots.length-1][1];
  }
  document.querySelectorAll('.chart').forEach(function (root) {
    var d = JSON.parse(root.querySelector('.chart-data').textContent);
    var svg = root.querySelector('svg'), hit = root.querySelector('.c-hit'),
        cross = root.querySelector('.c-cross'), tip = root.querySelector('.chart-tip');
    var ML = 56, W = 640, PLOT = W - ML - 14;
    var idx = null;
    function centers() {
      return d.bins.map(function (b) { return (b[0] + b[1]) / 2; });
    }
    function show(i, clientX, clientY) {
      var c = centers(); i = Math.max(0, Math.min(c.length - 1, i)); idx = i;
      var m = c[i], b = d.bins[i];
      var xView = ML + (m + d.half) / (2 * d.half) * PLOT;
      cross.setAttribute('x1', xView); cross.setAttribute('x2', xView);
      cross.setAttribute('visibility', 'visible');
      var price = d.spot * (1 + m), pnl = payoffAt(d.knots, m);
      tip.textContent = '';
      var v = document.createElement('div'); v.className = 'v';
      v.textContent = (pnl >= 0 ? 'make ' : 'lose ') + fmtUsd(Math.abs(pnl));
      var l1 = document.createElement('div');
      l1.textContent = 'if it moves ' + (m >= 0 ? '+' : '') + (100 * m).toFixed(1) +
                       '% (to $' + price.toFixed(2) + ')';
      var l2 = document.createElement('div');
      l2.textContent = 'past reports near here: ' + (b[2] + b[3]) + ' of ' + d.total +
                       ' (' + b[2] + ' win / ' + b[3] + ' loss)';
      tip.appendChild(v); tip.appendChild(l1); tip.appendChild(l2);
      tip.hidden = false;
      var r = root.getBoundingClientRect();
      var left = Math.min(clientX - r.left + 14, r.width - 240);
      tip.style.left = Math.max(0, left) + 'px';
      tip.style.top = (clientY - r.top - 10) + 'px';
    }
    function hide() { cross.setAttribute('visibility', 'hidden'); tip.hidden = true; idx = null; }
    hit.addEventListener('pointermove', function (ev) {
      var box = svg.getBoundingClientRect();
      var xr = (ev.clientX - box.left) / box.width * W;
      var m = (xr - ML) / PLOT * 2 * d.half - d.half;
      var c = centers(), best = 0;
      c.forEach(function (v, i) { if (Math.abs(v - m) < Math.abs(c[best] - m)) best = i; });
      show(best, ev.clientX, ev.clientY);
    });
    hit.addEventListener('pointerleave', hide);
    svg.addEventListener('keydown', function (ev) {
      var box = svg.getBoundingClientRect();
      if (ev.key === 'ArrowRight' || ev.key === 'ArrowLeft') {
        ev.preventDefault();
        var next = idx === null ? Math.floor(d.bins.length / 2)
                                : idx + (ev.key === 'ArrowRight' ? 1 : -1);
        show(next, box.left + box.width / 2, box.top + 40);
      } else if (ev.key === 'Escape') { hide(); }
    });
    svg.addEventListener('blur', hide);
  });
})();
"""
