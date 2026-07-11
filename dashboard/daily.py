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
import logging
from datetime import date

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.dashboard")

CSV_COLUMNS = [
    "ticker", "name", "sector", "earnings_date", "session",
    "implied_move_mid", "implied_move_ask", "fair_move", "ci_low", "ci_high",
    "edge", "z", "score", "structure", "detail", "entry_side", "entry_price",
    "max_gain", "max_loss", "spread_pct", "spread_cost_pct_of_edge",
    "open_interest", "conf_mult", "n_events", "screened", "screen_reason", "flags",
    "spot", "expiry", "atm_strike", "straddle_bid", "straddle_mid", "straddle_ask",
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


HEADERS = (
    "<tr><th>Ticker</th><th>Earnings</th><th>Implied (mid)</th><th>Fair ± CI (80%)</th>"
    "<th>Edge</th><th>Score</th><th>Structure</th><th>Max gain / loss</th>"
    "<th>Spread / edge</th><th>Conf</th><th>n</th><th>Flags</th></tr>"
)

CSS = """
:root { --ink:#1a1d21; --muted:#697077; --line:#e0e3e7; --bg:#ffffff; --card:#f6f7f8; }
@media (prefers-color-scheme: dark) {
  :root { --ink:#e6e8ea; --muted:#9aa1a9; --line:#33383e; --bg:#17191c; --card:#212429; }
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
"""


def render_html(scored: pd.DataFrame, run_date: date, banner: str = "") -> str:
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
<h2>Ranked (passing liquidity screen)</h2>
<div class=tablewrap><table>{HEADERS}{live_rows or '<tr><td colspan=12>none</td></tr>'}</table></div>
<h2>Screened out (spread &gt; {config.MAX_SPREAD_PCT:.0%} of straddle, OI &lt; {config.MIN_OPEN_INTEREST}, or dead quotes)</h2>
<div class=tablewrap><table>{HEADERS}{killed_rows or '<tr><td colspan=12>none</td></tr>'}</table></div>
</body></html>
"""


def run(
    scored: pd.DataFrame | None = None,
    run_date: date | None = None,
    out_dir=None,
    banner: str = "",
) -> tuple:
    config.ensure_dirs()
    run_date = run_date or date.today()
    out_dir = out_dir or config.DASHBOARD_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    if scored is None:
        scored = pd.read_parquet(config.SCORED_PARQUET)

    html_path = out_dir / f"daily_{run_date}.html"
    csv_path = out_dir / f"daily_{run_date}.csv"
    html_path.write_text(render_html(scored, run_date, banner=banner))
    cols = [c for c in CSV_COLUMNS if c in scored.columns]
    scored[cols].to_csv(csv_path, index=False)
    log.info("dashboard -> %s and %s", html_path, csv_path)
    return html_path, csv_path


if __name__ == "__main__":
    config.setup_logging()
    run()
