"""Season postmortem for the picks competition (plan_picks_tab §3).

Generates reports/picks_postmortem.md: final leaderboard + awards, the
framework scorecard (did the value gates, crowding scores, and T-1 implied
moves say anything true about these 11 names?), a one-paragraph per-name
autopsy, and the honest caveat the plan demands. Runnable at any point in
the season — before the end date it is clearly labeled provisional.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from common import config
from dashboard.picks_tab import _realized_move, _risk_stats, leaderboard_frame, load_inputs

log = logging.getLogger("ete.picks_postmortem")

REPORT_PATH = config.REPO_ROOT / "reports" / "picks_postmortem.md"


def _per_name(data: dict) -> pd.DataFrame:
    """One row per pick: return, contribution, engine verdicts, event outcome."""
    inception, positions = data["inception"], data.get("positions")
    events = data.get("events")
    enr = (data.get("enriched").set_index("ticker")
           if data.get("enriched") is not None else pd.DataFrame())
    j = (data.get("journal").set_index("ticker")
         if data.get("journal") is not None and len(data.get("journal")) else pd.DataFrame())
    evs = events.set_index("ticker") if events is not None else pd.DataFrame()

    latest = pd.DataFrame()
    if positions is not None and len(positions):
        latest = positions[positions["date"] == positions["date"].max()].set_index("ticker")

    rows = []
    for pos in inception[~inception["portfolio"].str.startswith("BM:")].itertuples(index=False):
        t = pos.ticker
        cur = latest.loc[t] if t in getattr(latest, "index", []) else None
        value = float(cur["value"] + cur["cash"]) if cur is not None else np.nan
        row = {
            "portfolio": pos.portfolio, "ticker": t,
            "ret": value / pos.allocation - 1.0 if np.isfinite(value) else np.nan,
            "contrib": value - pos.allocation if np.isfinite(value) else np.nan,
            "value_verdict": str(enr.loc[t, "value_verdict"]) if t in getattr(enr, "index", []) else "n/a",
            "velocity_z": float(enr.loc[t, "velocity_z"]) if t in getattr(enr, "index", []) else np.nan,
            "earnings_date": None, "implied": np.nan, "fair": np.nan,
            "realized": np.nan, "impact": np.nan,
        }
        if t in getattr(evs, "index", []):
            e = evs.loc[t]
            if pd.notna(e["earnings_date"]):
                ev = pd.Timestamp(e["earnings_date"]).date()
                row["earnings_date"] = ev
                row["realized"], row["impact"] = _realized_move(positions, t, ev, e["session"])
        if t in getattr(j, "index", []):
            jr = j.loc[t]
            row["implied"] = float(jr.get("implied_move_mid", np.nan))
            row["fair"] = float(jr.get("fair_move", np.nan))
        rows.append(row)
    return pd.DataFrame(rows)


def _fmt(v, spec=".1%", dash="—"):
    return format(v, spec) if v is not None and np.isfinite(v) else dash


def _awards(nav: pd.DataFrame, per: pd.DataFrame) -> list[str]:
    out = []
    stats = {}
    for p in ["John", "PaulMeme"]:
        sub = nav[nav["portfolio"] == p]
        if len(sub):
            stats[p] = _risk_stats(sub.sort_values("date"), None)
    with_vol = {p: s for p, s in stats.items() if np.isfinite(s.get("vol", np.nan)) and s["vol"] > 0}
    if with_vol:
        best = max(with_vol, key=lambda p: with_vol[p]["ret"] / with_vol[p]["vol"])
        s = with_vol[best]
        out.append(f"- **Best risk-adjusted:** {best} ({s['ret'] / s['vol']:.2f} return/vol)")
    else:
        out.append("- **Best risk-adjusted:** n/a (needs ≥5 trading days of NAV)")
    if per["contrib"].notna().any():
        top = per.loc[per["contrib"].idxmax()]
        out.append(f"- **Best single-name contribution:** {top['ticker']} ({top['portfolio']}), "
                   f"{top['contrib']:+,.0f}$ ({_fmt(top['ret'])})")
    if stats:
        small = min(stats, key=lambda p: abs(stats[p].get("maxdd", 0.0)))
        out.append(f"- **Smallest max drawdown:** {small} ({_fmt(stats[small].get('maxdd'))})")
    return out


def _framework_scorecard(per: pd.DataFrame) -> list[str]:
    lines = ["## Framework scorecard", ""]
    scored = per[per["ret"].notna()]

    is_warned = scored["value_verdict"].str.contains("no moat|eject|disqualif", na=False)
    warned = scored[is_warned]
    passed = scored[~is_warned
                    & scored["value_verdict"].str.startswith(("pass", "watch", "buy"), na=False)]
    if len(warned) and len(passed):
        lines.append(
            f"- **Value gates:** names the gates warned about ({', '.join(warned['ticker'])}) "
            f"average {_fmt(warned['ret'].mean())}; names that passed or made watch "
            f"({', '.join(passed['ticker'])}) average {_fmt(passed['ret'].mean())}."
        )
    else:
        lines.append("- **Value gates:** not enough covered names with returns yet.")

    crowd = scored[scored["velocity_z"].notna()]
    # rank correlation on day-1 all-zero returns is pure float noise — require
    # actual dispersion before claiming a number
    if len(crowd) >= 4 and crowd["ret"].notna().sum() >= 4 and crowd["ret"].std() > 1e-6:
        rho = crowd["velocity_z"].corr(crowd["ret"], method="spearman")
        lines.append(
            f"- **Crowding:** Spearman rank correlation of mention-velocity z vs return "
            f"across {len(crowd)} names: {rho:+.2f} (positive = crowded names won)."
        )
    else:
        lines.append("- **Crowding:** needs at least 4 names with both a z-score and a return.")

    cal = per[per["implied"].notna() & per["realized"].notna()]
    if len(cal):
        inside = (cal["realized"].abs() <= cal["implied"]).mean()
        ratio = (cal["realized"].abs() / cal["implied"]).median()
        lines.append(
            f"- **T-1 implied moves:** {len(cal)} events resolved; {inside:.0%} landed inside "
            f"the implied move; median |realized|/implied = {ratio:.2f}."
        )
    else:
        lines.append("- **T-1 implied moves:** no frozen events have resolved yet.")
    return lines


def build_report(today: date | None = None, data: dict | None = None) -> str:
    today = today or date.today()
    data = data or load_inputs()
    rules, nav = data.get("rules"), data.get("nav")
    if rules is None or nav is None or nav.empty:
        return ("# Picks postmortem\n\nNo NAV history yet — run `picks.nav` first.\n")

    end = date.fromisoformat(rules["rules"]["end_date"])
    final = today >= end
    status = "FINAL" if final else f"SEASON IN PROGRESS — provisional through {nav['date'].max()}"
    lb = leaderboard_frame(nav)
    per = _per_name(data)

    lines = [
        "# John and Paul picks — postmortem",
        "",
        f"_{status}. Pre-registered {rules['rules']['inception_earliest']}; "
        f"season ends {end}. Paper only._",
        "",
        "## Leaderboard",
        "",
        "| rank | portfolio | NAV | total return |",
        "|---|---|---|---|",
    ]
    for r in lb.itertuples(index=False):
        lines.append(f"| {r.rank} | {r.portfolio} | ${r.nav:,.0f} | {_fmt(r.total_return, '+.2%')} |")
    lines += ["", "### Awards" + (" (provisional)" if not final else ""), ""]
    lines += _awards(nav, per)
    lines += ["", *_framework_scorecard(per), "", "## Per-name autopsies", ""]

    for r in per.sort_values(["portfolio", "contrib"], ascending=[True, False]).itertuples(index=False):
        ev = (f"reported {r.earnings_date}: realized {_fmt(r.realized, '+.1%')} vs "
              f"implied {_fmt(r.implied)} (fair {_fmt(r.fair)})"
              if r.earnings_date and np.isfinite(r.realized)
              else (f"reports {r.earnings_date}" if r.earnings_date else "earnings date unresolved"))
        lines.append(
            f"- **{r.ticker}** ({r.portfolio}): {_fmt(r.ret, '+.1%')} "
            f"({_fmt(r.contrib, '+,.0f', '—')}$ contribution). Value engine: {r.value_verdict}. "
            f"Crowding z: {_fmt(r.velocity_z, '+.1f')}. Earnings: {ev}. "
            f"_Thesis-relevant news: fill in by hand — the pipeline doesn't read headlines._"
        )

    lines += [
        "",
        "## The honest caveat",
        "",
        "11 names over 7 weeks is an entertainment-grade sample. The framework scorecard "
        "above is anecdote collection for the journals — evidence about process discipline, "
        "not statistical validation of any engine. Nothing here supports sizing real money.",
        "",
    ]
    return "\n".join(lines)


def run(today: date | None = None) -> str:
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    report = build_report(today=today)
    REPORT_PATH.write_text(report)
    log.info("picks postmortem -> %s", REPORT_PATH)
    return report


if __name__ == "__main__":
    config.setup_logging()
    print(run())
