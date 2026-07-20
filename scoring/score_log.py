"""Score resolved pre-registrations against what actually happened (plan §4).

For every frozen row in log/predictions.csv whose event has passed:
  * realized earnings move with the same BMO/AMC alignment the model used;
  * calibration: |realized| vs the frozen implied and fair moves;
  * expiry P&L for registered structures (iron fly / straddle / strangle),
    settled at the expiry-day close, entries at the frozen realistic prices.

The log rows are never modified — this reads, scores, and writes a dated
scorecard to reports/. One week of events is directional evidence only; the
season-end review (plan §4) is the real test.
"""

from __future__ import annotations

import logging
import re
from datetime import date

import numpy as np
import pandas as pd

from common import config
from features.moves import _event_move

log = logging.getLogger("ete.score_log")

REPORTS_DIR = config.REPO_ROOT / "reports"

FLY_RE = re.compile(r"short (\d+\.?\d*) straddle @ bid, long (\d+\.?\d*)P / (\d+\.?\d*)C @ ask")
STRADDLE_RE = re.compile(r"long (\d+\.?\d*) straddle @ ask")
STRANGLE_RE = re.compile(r"long (\d+\.?\d*)P / (\d+\.?\d*)C @ ask")


def structure_pnl(row: pd.Series, settle: float) -> float | None:
    """Expiry P&L per contract at settle price; None if not parseable/tradeable."""
    detail = str(row.get("detail", ""))
    entry = float(row["entry_price"]) if np.isfinite(row.get("entry_price", np.nan)) else None
    if entry is None:
        return None
    m = FLY_RE.search(detail)
    if m and row["structure"] == "iron fly":
        atm, put_w, call_w = map(float, m.groups())
        intrinsic = min(max(settle - atm, 0.0), call_w - atm) + min(max(atm - settle, 0.0), atm - put_w)
        return entry - 100.0 * intrinsic
    m = STRADDLE_RE.search(detail)
    if m and row["structure"] == "long straddle":
        atm = float(m.group(1))
        return 100.0 * abs(settle - atm) - entry
    m = STRANGLE_RE.search(detail)
    if m and row["structure"] == "long strangle":
        put_k, call_k = map(float, m.groups())
        intrinsic = max(settle - call_k, 0.0) + max(put_k - settle, 0.0)
        return 100.0 * intrinsic - entry
    return None


def score(predictions: pd.DataFrame, prices: pd.DataFrame, today: date) -> pd.DataFrame:
    """One scored row per resolved prediction."""
    px_by_ticker = {
        t: (g["date"].to_numpy(dtype="datetime64[D]"), g["adj_close"].to_numpy(dtype=float),
            dict(zip(g["date"].dt.strftime("%Y-%m-%d"), g["adj_close"])))
        for t, g in prices.sort_values("date").groupby("ticker")
    }
    rows = []
    for r in predictions.itertuples(index=False):
        ev_date = date.fromisoformat(str(r.earnings_date))
        if ev_date >= today or r.ticker not in px_by_ticker:
            continue
        dates, closes, by_day = px_by_ticker[r.ticker]
        res = _event_move(dates, closes, ev_date, str(r.session))
        if res is None:
            continue
        realized, _conf = res
        implied = float(r.implied_move_mid)
        fair = float(r.fair_move)
        expiry = str(r.expiry)
        settle = by_day.get(expiry)
        pnl = structure_pnl(pd.Series(r._asdict()), settle) if (
            settle is not None and expiry <= today.isoformat()
        ) else None
        rows.append(
            {
                "ticker": r.ticker,
                "earnings_date": ev_date,
                "session": r.session,
                "structure": r.structure,
                "implied_frozen": implied,
                "fair_frozen": fair,
                "realized_move": realized,
                "abs_realized": abs(realized),
                "inside_implied": abs(realized) <= implied,
                "realized_over_implied": abs(realized) / implied if implied > 0 else np.nan,
                "realized_over_fair": abs(realized) / fair if fair > 0 else np.nan,
                "entry_price": r.entry_price,
                "settle": settle,
                "pnl": pnl,
                "screened": bool(r.screened),
            }
        )
    return pd.DataFrame(rows)


def render_scorecard(scored: pd.DataFrame, today: date) -> str:
    traded = scored[scored["pnl"].notna()]
    L = [
        f"# Options pre-registration scorecard — through {today}",
        "",
        f"{len(scored)} resolved events; {len(traded)} carried registered structures "
        "(entries frozen at registration prices — buy at ask / sell at bid).",
        "",
        "## Calibration (all resolved events)",
        f"- realized |move| landed inside the frozen implied move in "
        f"**{100 * scored['inside_implied'].mean():.0f}%** of events "
        "(vol premium says this should exceed ~50%)",
        f"- median realized/implied: **{scored['realized_over_implied'].median():.2f}** · "
        f"median realized/fair: **{scored['realized_over_fair'].median():.2f}**",
        "",
        "## Structure P&L (expiry settlement, 1 contract per registration)",
    ]
    if traded.empty:
        L.append("- no structures reached expiry yet")
    else:
        wins = (traded["pnl"] > 0).sum()
        L += [
            f"- **{wins}/{len(traded)} winners · net P&L ${traded['pnl'].sum():,.0f}** "
            f"(gross credits/debits ${traded['entry_price'].sum():,.0f})",
            "",
            "| Ticker | Event | Structure | Implied | Realized | P&L |",
            "|---|---|---|---|---|---|",
        ]
        for r in traded.sort_values("pnl", ascending=False).itertuples(index=False):
            L.append(
                f"| {r.ticker} | {r.earnings_date} {r.session} | {r.structure} | "
                f"±{100 * r.implied_frozen:.1f}% | {100 * r.realized_move:+.1f}% | "
                f"${r.pnl:,.0f} |"
            )
    L += [
        "",
        "_One week is directional evidence, not a verdict (plan §4). The season-end_",
        "_review scores calibration bands, edge-vs-P&L regression, and cost drag._",
    ]
    return "\n".join(L)


def run(today: date | None = None) -> pd.DataFrame:
    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()
    import yfinance as yf

    today = today or date.today()
    preds = pd.read_csv(config.PREDICTIONS_CSV)
    tickers = sorted(set(preds["ticker"]))
    raw = yf.download(tickers, start="2026-06-25", auto_adjust=True, progress=False)
    close = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    prices = (
        close.stack().rename("adj_close").reset_index()
        .rename(columns={"level_1": "ticker", "Ticker": "ticker", "Date": "date"})
    )
    prices["date"] = pd.to_datetime(prices["date"])
    scored = score(preds, prices, today)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / "options_scorecard.md"
    out.write_text(render_scorecard(scored, today))
    scored.to_parquet(config.DATA_DIR / "scorecard.parquet", index=False)
    log.info("scorecard: %d resolved events -> %s", len(scored), out)
    return scored


if __name__ == "__main__":
    config.setup_logging()
    run()
