"""'John and Paul picks' tab — the pre-registered $10k vs $10k horse race.

Four panels per plan_picks_tab §2: scoreboard header, NAV race chart with
earnings flags, holdings tables with the three engine-signal columns, the
earnings event log, and attribution/risk (incl. the beta-to-QQQ "luck vs
design" note). Renders sensibly on day 1 (single NAV point) and with any
sibling file missing.
"""

from __future__ import annotations

import html
import logging
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.picks_tab")

TBILL_ANNUAL = 0.04  # Sharpe-style ratio assumption, stated in the panel
MIN_RISK_DAYS = 5    # realized vol / beta need at least this many daily returns

COLORS = {"John": "#4f8ff7", "PaulMeme": "#f7734f", "BM:SPY": "#8a8f98", "BM:QQQ": "#b9a44c"}
CONTESTANTS = ["John", "PaulMeme"]


def load_inputs() -> dict:
    def _opt(path, reader=pd.read_parquet):
        try:
            return reader(path) if path.exists() else None
        except Exception as exc:  # a broken sibling file must not kill the page
            log.warning("picks tab: could not read %s: %s", path, exc)
            return None

    from picks.events import PICKS_EVENTS_PARQUET, PICKS_PREDICTIONS_CSV
    from picks.enrich import ENRICHED_PARQUET
    from picks.nav import INCEPTION_PARQUET, NAV_PARQUET, POSITIONS_PARQUET, load_rules

    return {
        "rules": load_rules() if (config.REPO_ROOT / "config" / "picks.yaml").exists() else None,
        "nav": _opt(NAV_PARQUET),
        "inception": _opt(INCEPTION_PARQUET),
        "positions": _opt(POSITIONS_PARQUET),
        "events": _opt(PICKS_EVENTS_PARQUET),
        "enriched": _opt(ENRICHED_PARQUET),
        "journal": _opt(PICKS_PREDICTIONS_CSV, pd.read_csv),
    }


def _money(v: float) -> str:
    return f"${v:,.0f}"


def _pct(v: float, digits: int = 1) -> str:
    return f"{v:+.{digits}%}" if np.isfinite(v) else "—"


# ---------------------------------------------------------------- scoreboard --
def scoreboard(nav: pd.DataFrame, rules: dict, today: date) -> str:
    last_day = nav["date"].max()
    latest = nav[nav["date"] == last_day].set_index("portfolio")["nav"]
    dates = sorted(nav["date"].unique())
    prev = (
        nav[nav["date"] == dates[-2]].set_index("portfolio")["nav"]
        if len(dates) > 1 else None
    )
    end = date.fromisoformat(rules["rules"]["end_date"])
    days_left = max(len(pd.bdate_range(today, end)) - 1, 0)

    tiles = []
    for p in [*CONTESTANTS, "BM:SPY", "BM:QQQ"]:
        v = float(latest.get(p, np.nan))
        chg = (v / float(prev[p]) - 1.0) if prev is not None and p in prev.index else np.nan
        label = p.replace("BM:", "") + (" (benchmark)" if p.startswith("BM:") else "")
        tiles.append(
            f'<div class=tile><div class=v style="color:{COLORS[p]}">{_money(v)}</div>'
            f'<div class=k>{html.escape(label)} · day {_pct(chg)}</div></div>'
        )
    j, p = float(latest.get("John", np.nan)), float(latest.get("PaulMeme", np.nan))
    leader, lag = ("John", p) if j >= p else ("PaulMeme", j)
    lead = abs(j - p)
    tiles.append(
        f'<div class=tile><div class=v>{html.escape(leader)}</div>'
        f'<div class=k>leads by {_money(lead)} ({lead / lag:+.2%})</div></div>'
    )
    tiles.append(
        f'<div class=tile><div class=v>{days_left}</div>'
        f'<div class=k>trading days left (ends {end})</div></div>'
    )
    return (
        f"<div class=tiles>{''.join(tiles)}</div>"
        f"<p class=muted>Through {last_day} close · pre-registered {rules['rules']['inception_earliest']}, "
        f"buy-and-hold, dividends as uninvested cash · winner: highest ending NAV.</p>"
    )


# ---------------------------------------------------------------- race chart --
def race_chart(nav: pd.DataFrame, events: pd.DataFrame | None, rules: dict) -> str:
    W, H, ML, MR, MT, MB = 880, 320, 56, 10, 14, 34
    start = pd.Timestamp(rules["rules"]["inception_earliest"])
    end = pd.Timestamp(rules["rules"]["end_date"])
    if events is not None and events["earnings_date"].notna().any():
        end = max(end, pd.to_datetime(events["earnings_date"]).max())
    span = max((end - start).days, 1)

    navs = nav.copy()
    navs["ts"] = pd.to_datetime(navs["date"])
    ys = navs["nav"].tolist() + [10_000.0]
    ylo, yhi = min(ys) * 0.985, max(ys) * 1.015

    def x(ts):
        return ML + (W - ML - MR) * (ts - start).days / span

    def y(v):
        return MT + (H - MT - MB) * (1 - (v - ylo) / (yhi - ylo))

    parts = [
        "<style>"
        ".racechart{width:100%;max-width:880px;background:var(--card);"
        "border:1px solid var(--line);border-radius:10px}"
        ".racechart .grid{stroke:var(--line);stroke-width:0.6}"
        ".racechart .lbl{fill:var(--muted);font-size:10px}"
        ".racechart .leg{fill:var(--ink);font-size:10px}"
        "</style>",
        f'<svg class="racechart" viewBox="0 0 {W} {H}" role="img" aria-label="NAV race">',
    ]
    # y grid
    for gv in np.linspace(ylo, yhi, 5):
        gy = y(gv)
        parts.append(f'<line class="grid" x1="{ML}" y1="{gy:.1f}" x2="{W - MR}" y2="{gy:.1f}" />')
        parts.append(f'<text class="lbl" x="{ML - 6}" y="{gy + 3:.1f}" text-anchor="end">'
                     f'${gv / 1000:.1f}k</text>')
    # month ticks
    for m in pd.date_range(start, end, freq="MS"):
        gx = x(m)
        parts.append(f'<line class="grid" x1="{gx:.1f}" y1="{MT}" x2="{gx:.1f}" y2="{H - MB}" />')
        parts.append(f'<text class="lbl" x="{gx:.1f}" y="{H - MB + 14}" text-anchor="middle">'
                     f'{m.strftime("%b")}</text>')
    # lines
    for p, grp in navs.groupby("portfolio"):
        grp = grp.sort_values("ts")
        pts = " ".join(f"{x(r.ts):.1f},{y(r.nav):.1f}" for r in grp.itertuples(index=False))
        color = COLORS.get(p, "#888")
        dash = ' stroke-dasharray="5 4"' if p.startswith("BM:") else ""
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" '
                     f'stroke-width="2"{dash} />')
        last = grp.iloc[-1]
        parts.append(f'<circle cx="{x(last["ts"]):.1f}" cy="{y(last["nav"]):.1f}" r="3" '
                     f'fill="{color}" />')
    # earnings flags: on the owning line once resolved, else on the bottom axis
    if events is not None:
        last_nav_ts = navs["ts"].max()
        flagrow = 0
        for r in events.dropna(subset=["earnings_date"]).sort_values("earnings_date").itertuples(index=False):
            ts = pd.Timestamp(r.earnings_date)
            if not (start <= ts <= end):
                continue
            gx = x(ts)
            color = COLORS.get(r.portfolio, "#888")
            own = navs[(navs["portfolio"] == r.portfolio) & (navs["ts"] <= ts)]
            if ts <= last_nav_ts and len(own):
                gy = y(float(own.sort_values("ts").iloc[-1]["nav"]))
                parts.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="4" fill="none" '
                             f'stroke="{color}" stroke-width="1.6">'
                             f'<title>{r.ticker} reports {r.earnings_date}</title></circle>')
            else:
                gy = H - MB
                parts.append(f'<path d="M{gx:.1f} {gy - 7} l4 7 l-8 0 z" fill="{color}">'
                             f'<title>{r.ticker} reports {r.earnings_date} ({r.session})</title></path>')
            ly = MT + 10 + (flagrow % 3) * 11
            flagrow += 1
            parts.append(f'<line x1="{gx:.1f}" y1="{ly + 3}" x2="{gx:.1f}" y2="{gy - 7:.1f}" '
                         f'stroke="{color}" stroke-width="0.5" opacity="0.45" />')
            parts.append(f'<text x="{gx:.1f}" y="{ly}" text-anchor="middle" font-size="9" '
                         f'fill="{color}">{r.ticker}</text>')
    # legend
    lx = ML + 8
    for p in ["John", "PaulMeme", "BM:SPY", "BM:QQQ"]:
        parts.append(f'<rect x="{lx}" y="{H - 12}" width="10" height="3" fill="{COLORS[p]}" />')
        parts.append(f'<text class="leg" x="{lx + 14}" y="{H - 8}">{p.replace("BM:", "")}</text>')
        lx += 14 + 8 * len(p.replace("BM:", "")) + 18
    parts.append("</svg>")
    return (
        "<h2>NAV race</h2>"
        + "".join(parts)
        + "<p class=muted>Flags mark each name's earnings date on the portfolio that owns it "
          "(▲ = still ahead). Benchmarks dashed.</p>"
    )


# ------------------------------------------------------------------ holdings --
def holdings_table(
    pname: str,
    inception: pd.DataFrame,
    positions: pd.DataFrame | None,
    events: pd.DataFrame | None,
    enriched: pd.DataFrame | None,
) -> str:
    inc = inception[inception["portfolio"] == pname]
    latest = pd.DataFrame()
    if positions is not None and len(positions):
        latest = positions[
            (positions["portfolio"] == pname)
            & (positions["date"] == positions["date"].max())
        ].set_index("ticker")
    evs = events.set_index("ticker") if events is not None else pd.DataFrame()
    enr = enriched.set_index("ticker") if enriched is not None else pd.DataFrame()
    total_value = float(latest["value"].sum() + latest["cash"].sum()) if len(latest) else np.nan

    rows = []
    for pos in inc.itertuples(index=False):
        t = pos.ticker
        cur = latest.loc[t] if t in getattr(latest, "index", []) else None
        last_px = float(cur["close"]) if cur is not None else np.nan
        value = float(cur["value"]) if cur is not None else np.nan
        cash = float(cur["cash"]) if cur is not None else 0.0
        ret = (value + cash) / pos.allocation - 1.0 if np.isfinite(value) else np.nan
        contrib = value + cash - pos.allocation if np.isfinite(value) else np.nan
        w_now = value / total_value if np.isfinite(value) and total_value else np.nan
        w_0 = pos.allocation / inc["allocation"].sum()
        drift = w_now - w_0 if np.isfinite(w_now) else np.nan
        if t in getattr(evs, "index", []):
            e = evs.loc[t]
            when = f"{e['earnings_date']} {e['session']}" if pd.notna(e["earnings_date"]) else "unresolved"
            if e["status"] == "conflict":
                when += " ⚠︎"
        else:
            when = "n/a"
        get = (lambda c: html.escape(str(enr.loc[t, c]))
               if t in getattr(enr, "index", []) else "n/a")
        rows.append(
            f"<tr><td><b>{t}</b></td><td>{pos.shares:.3f}</td>"
            f"<td>${pos.entry_close:,.2f}</td><td>{f'${last_px:,.2f}' if np.isfinite(last_px) else '—'}</td>"
            f"<td>{_money(value + cash) if np.isfinite(value) else '—'}</td>"
            f"<td>{_pct(ret, 2)}</td><td>{f'{contrib:+,.0f}' if np.isfinite(contrib) else '—'}</td>"
            f"<td>{f'{100 * drift:+.1f}pp' if np.isfinite(drift) else '—'}</td>"
            f"<td>{html.escape(when)}</td>"
            f"<td class=sig>{get('value_verdict')}</td>"
            f"<td class=sig>{get('crowding')}</td>"
            f"<td class=sig>{get('earnings_edge')}</td></tr>"
        )
    head = ("<tr><th>name</th><th>shares</th><th>entry</th><th>last</th><th>value</th>"
            "<th>ret</th><th>contrib $</th><th>drift</th><th>next earnings</th>"
            "<th>value verdict</th><th>crowding</th><th>earnings edge</th></tr>")
    title = f"{pname} — {_money(total_value)}" if np.isfinite(total_value) else pname
    return (
        f"<h3 style='color:{COLORS[pname]}'>{html.escape(title)}</h3>"
        f"<div class=tablewrap><table>{head}{''.join(rows)}</table></div>"
    )


# ----------------------------------------------------------------- event log --
def _realized_move(positions: pd.DataFrame | None, ticker: str, ev: date, session: str):
    """(realized move, NAV impact $) over the reaction session, or (nan, nan)."""
    if positions is None or not len(positions):
        return np.nan, np.nan
    px = positions[positions["ticker"] == ticker].sort_values("date")
    if px.empty:
        return np.nan, np.nan
    dates = px["date"].tolist()
    after = [d for d in dates if d > ev]
    onor = [d for d in dates if d <= ev]
    if session == "BMO":
        if ev not in dates or not [d for d in onor if d < ev]:
            return np.nan, np.nan
        d0, d1 = max(d for d in onor if d < ev), ev
    else:  # AMC or unknown (treated as AMC)
        if not onor or not after:
            return np.nan, np.nan
        d0, d1 = max(onor), min(after)
    p0 = float(px[px["date"] == d0]["close"].iloc[0])
    r1 = px[px["date"] == d1].iloc[0]
    return float(r1["close"]) / p0 - 1.0, (float(r1["close"]) - p0) * float(r1["shares"])


def event_log(
    events: pd.DataFrame | None,
    journal: pd.DataFrame | None,
    positions: pd.DataFrame | None,
    today: date,
) -> str:
    if events is None or events.empty:
        return ("<h2>Earnings event log</h2><p class=muted>No resolved dates yet — "
                "run <code>picks.events</code>.</p>")
    j = (journal.set_index("ticker") if journal is not None and len(journal)
         else pd.DataFrame())
    rows = []
    for r in events.sort_values("earnings_date", na_position="last").itertuples(index=False):
        ev = pd.Timestamp(r.earnings_date).date() if pd.notna(r.earnings_date) else None
        frozen = r.ticker in getattr(j, "index", [])
        impl = fair = "—"
        if frozen:
            row = j.loc[r.ticker]
            iv, fv = row.get("implied_move_mid"), row.get("fair_move")
            impl = f"{iv:.1%}" if np.isfinite(iv) else "—"
            fair = f"{fv:.1%}" if np.isfinite(fv) else "—"
        realized, impact = (_realized_move(positions, r.ticker, ev, r.session)
                            if ev else (np.nan, np.nan))
        if ev is None:
            state = "unresolved date"
        elif np.isfinite(realized):
            state = "resolved"
        elif frozen:
            state = "frozen at T-1"
        elif ev <= today:
            state = "resolved (move pending)"
        else:
            state = "pending"
        status = f" ⚠︎ {html.escape(r.sources)}" if r.status == "conflict" else ""
        rows.append(
            f"<tr><td>{html.escape(r.portfolio)}</td><td><b>{r.ticker}</b></td>"
            f"<td>{ev or '—'}{status}</td><td>{r.session}</td>"
            f"<td>{impl}</td><td>{fair}</td>"
            f"<td>{_pct(realized) if np.isfinite(realized) else '—'}</td>"
            f"<td>{f'{impact:+,.0f}' if np.isfinite(impact) else '—'}</td>"
            f"<td>{state}</td></tr>"
        )
    head = ("<tr><th>portfolio</th><th>name</th><th>date</th><th>session</th>"
            "<th>implied (T-1)</th><th>fair (T-1)</th><th>realized</th>"
            "<th>NAV impact $</th><th>state</th></tr>")
    return (
        "<h2>Earnings event log</h2>"
        "<p class=muted>Implied/fair freeze at T-1 into the journal (first write wins); "
        "realized move measured over the reaction session. Dates resolve live with a "
        "two-source cross-check — ⚠︎ marks a source conflict.</p>"
        f"<div class=tablewrap><table>{head}{''.join(rows)}</table></div>"
    )


# ------------------------------------------------------------- attribution ---
def _risk_stats(navseries: pd.DataFrame, qqq: pd.Series | None) -> dict:
    s = navseries.sort_values("date")["nav"].astype(float)
    rets = s.pct_change().dropna()
    out = {"n": len(rets)}
    if len(rets) >= MIN_RISK_DAYS:
        out["vol"] = float(rets.std(ddof=1) * np.sqrt(252))
        excess = rets - TBILL_ANNUAL / 252
        out["sharpe"] = float(excess.mean() / rets.std(ddof=1) * np.sqrt(252)) if rets.std(ddof=1) else np.nan
    peak = s.cummax()
    out["maxdd"] = float((s / peak - 1.0).min()) if len(s) else np.nan
    out["ret"] = float(s.iloc[-1] / 10_000.0 - 1.0) if len(s) else np.nan
    if qqq is not None and len(rets) >= MIN_RISK_DAYS:
        qr = qqq.pct_change().dropna()
        n = min(len(rets), len(qr))
        if n >= MIN_RISK_DAYS and float(qr.tail(n).var(ddof=1)) > 0:
            out["beta"] = float(np.cov(rets.tail(n), qr.tail(n))[0, 1] / qr.tail(n).var(ddof=1))
    return out


def _concentration(positions: pd.DataFrame | None, pname: str) -> str:
    """Top contributor as % of total P&L (entry basis = frozen allocation)."""
    if positions is None or not len(positions):
        return "—"
    latest = positions[(positions["portfolio"] == pname)
                       & (positions["date"] == positions["date"].max())].copy()
    if latest.empty:
        return "—"
    # allocation is the true cost basis; shares may be split-adjusted, so
    # shares * entry_close would be wrong after a split
    from picks.nav import INCEPTION_PARQUET

    if not INCEPTION_PARQUET.exists():
        return "—"
    alloc = pd.read_parquet(INCEPTION_PARQUET).set_index(["portfolio", "ticker"])["allocation"]
    latest["pnl"] = [
        r["value"] + r["cash"] - float(alloc.get((pname, r["ticker"]), np.nan))
        for _, r in latest.iterrows()
    ]
    total = float(latest["pnl"].sum())
    if abs(total) < 1e-9 or latest["pnl"].isna().any():
        return "—"
    top = latest.loc[latest["pnl"].abs().idxmax()]
    return f"{top['ticker']} {100 * top['pnl'] / total:.0f}% of P&amp;L"


def attribution(nav: pd.DataFrame, positions: pd.DataFrame | None) -> str:
    qqq = nav[nav["portfolio"] == "BM:QQQ"].sort_values("date")["nav"].astype(float)
    na_short = f"n/a (&lt;{MIN_RISK_DAYS}d)"
    rows = []
    for p in [*CONTESTANTS, "BM:SPY", "BM:QQQ"]:
        sub = nav[nav["portfolio"] == p]
        if sub.empty:
            continue
        st = _risk_stats(sub, qqq if not p.startswith("BM:") else None)
        conc = _concentration(positions, p) if p in CONTESTANTS else "—"
        sharpe = f"{st['sharpe']:.2f}" if np.isfinite(st.get("sharpe", np.nan)) else na_short
        beta = f"{st['beta']:.2f}" if "beta" in st else (
            "—" if p.startswith("BM:") else na_short)
        vol = _pct(st["vol"]) if "vol" in st else na_short
        rows.append(
            f"<tr><td style='color:{COLORS[p]}'><b>{p.replace('BM:', '')}</b></td>"
            f"<td>{_pct(st.get('ret', np.nan), 2)}</td>"
            f"<td>{vol}</td><td>{sharpe}</td>"
            f"<td>{_pct(st.get('maxdd', np.nan))}</td>"
            f"<td>{beta}</td><td>{conc}</td></tr>"
        )
    head = ("<tr><th>portfolio</th><th>return</th><th>vol (ann.)</th>"
            f"<th>Sharpe-style (T-bill {TBILL_ANNUAL:.1%})</th><th>max DD</th>"
            "<th>beta to QQQ</th><th>top contributor</th></tr>")
    note = (
        "<p class=muted><b>Luck vs design:</b> John is ~half speculative small/mid "
        "(ACHR, QBTS, DSP, RXRX); PaulMeme is mega-cap + meme. Expect very different "
        "betas to QQQ — decompose any gap as return = β×QQQ + residual before "
        "crediting stock picking. The residual, not the headline, is the design part.</p>"
    )
    return ("<h2>Attribution &amp; risk</h2>"
            f"<div class=tablewrap><table>{head}{''.join(rows)}</table></div>" + note)


# ------------------------------------------------------------------- render --
def leaderboard_frame(nav: pd.DataFrame) -> pd.DataFrame:
    last_day = nav["date"].max()
    latest = nav[nav["date"] == last_day].copy()
    latest["total_return"] = latest["nav"] / 10_000.0 - 1.0
    latest = latest.sort_values("nav", ascending=False).reset_index(drop=True)
    latest["rank"] = latest.index + 1
    return latest[["rank", "portfolio", "date", "nav", "cash", "total_return"]]


def render_picks_tab(today: date, data: dict | None = None) -> str:
    data = data or load_inputs()
    rules, nav = data.get("rules"), data.get("nav")
    intro = (
        "<h2>John and Paul picks — the horse race</h2>"
        "<p class=muted>Two $10,000 paper portfolios, pre-registered, buy-and-hold through "
        "Q2 2026 earnings season. Doubles as a live test of the other three engines: their "
        "verdicts on these 11 names are frozen in the holdings tables below.</p>"
    )
    if rules is None or nav is None or nav.empty:
        return intro + ("<p class=muted>No NAV history yet — run <code>picks.nav</code> "
                        "to freeze inception.</p>")
    return (
        intro
        + scoreboard(nav, rules, today)
        + race_chart(nav, data.get("events"), rules)
        + "<h2>Holdings</h2>"
        + holdings_table("John", data["inception"], data.get("positions"),
                         data.get("events"), data.get("enriched"))
        + holdings_table("PaulMeme", data["inception"], data.get("positions"),
                         data.get("events"), data.get("enriched"))
        + event_log(data.get("events"), data.get("journal"), data.get("positions"), today)
        + attribution(nav, data.get("positions"))
    )
