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
        expired = settle is not None and expiry <= today.isoformat()
        pnl = structure_pnl(pd.Series(r._asdict()), settle) if expired else None

        # hypothetical one-lot straddle outcomes at the FROZEN quotes — the
        # systematic what-worked measure across every event, traded or not
        short_straddle = long_straddle = np.nan
        if expired and np.isfinite(r.atm_strike) and np.isfinite(r.straddle_bid):
            intrinsic = 100.0 * abs(settle - float(r.atm_strike))
            short_straddle = 100.0 * float(r.straddle_bid) - intrinsic   # sell at bid
            long_straddle = intrinsic - 100.0 * float(r.straddle_ask)    # buy at ask
        edge = (implied - fair) / fair if fair > 0 else np.nan
        if not np.isfinite(edge):
            bucket = "unscored"
        elif edge >= config.EDGE_NO_TRADE_BAND:
            bucket = "rich (model: short vol)"
        elif edge <= -config.EDGE_NO_TRADE_BAND:
            bucket = "cheap (model: long vol)"
        else:
            bucket = "neutral (model: no trade)"
        aligned = (
            short_straddle if bucket.startswith("rich")
            else long_straddle if bucket.startswith("cheap")
            else 0.0 if bucket.startswith("neutral") and np.isfinite(short_straddle)
            else np.nan
        )
        rows.append(
            {
                "ticker": r.ticker,
                "earnings_date": ev_date,
                "week": ev_date.isocalendar().week,
                "session": r.session,
                "structure": r.structure,
                "implied_frozen": implied,
                "fair_frozen": fair,
                "edge_frozen": edge,
                "edge_bucket": bucket,
                "realized_move": realized,
                "abs_realized": abs(realized),
                "inside_implied": abs(realized) <= implied,
                "realized_over_implied": abs(realized) / implied if implied > 0 else np.nan,
                "realized_over_fair": abs(realized) / fair if fair > 0 else np.nan,
                "entry_price": r.entry_price,
                "settle": settle,
                "pnl": pnl,
                "short_straddle_pnl": short_straddle,
                "long_straddle_pnl": long_straddle,
                "model_aligned_pnl": aligned,
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
    # ---- signal validity: does the edge bucket predict straddle P&L? -------
    hyp = scored[scored["short_straddle_pnl"].notna()]
    L += ["", "## Signal validity — hypothetical 1-lot straddles at frozen quotes", ""]
    if hyp.empty:
        L.append("- no expired events with usable frozen quotes yet")
    else:
        L += [
            "Sell-at-bid / buy-at-ask for EVERY resolved event, grouped by what the",
            "model said at registration. If the edge signal is real, rich events should",
            "make money shorted and cheap events should make money bought.",
            "",
            "| Model bucket | n | short-straddle P&L | long-straddle P&L | model-aligned P&L |",
            "|---|---|---|---|---|",
        ]
        for bucket, g in hyp.groupby("edge_bucket"):
            L.append(
                f"| {bucket} | {len(g)} | ${g['short_straddle_pnl'].sum():,.0f} | "
                f"${g['long_straddle_pnl'].sum():,.0f} | ${g['model_aligned_pnl'].sum():,.0f} |"
            )
        total_aligned = hyp["model_aligned_pnl"].sum()
        always_short = hyp["short_straddle_pnl"].sum()
        L += [
            "",
            f"- **Model-aligned total: ${total_aligned:,.0f}** vs always-short-everything "
            f"${always_short:,.0f} (n={len(hyp)})",
            "- Screened events are included: the screen protects fills, not signal scoring.",
        ]
        by_week = hyp.groupby("week")[["short_straddle_pnl", "model_aligned_pnl"]].sum()
        if len(by_week) > 1:
            L += ["", "| ISO week | short-all P&L | model-aligned P&L |", "|---|---|---|"]
            for wk, r in by_week.iterrows():
                L.append(
                    f"| {wk} | ${r['short_straddle_pnl']:,.0f} | ${r['model_aligned_pnl']:,.0f} |"
                )
    L += [
        "",
        "_Directional evidence, not a verdict (plan §4): hypothetical fills at frozen_",
        "_delayed quotes flatter both sides. Season-end review adds calibration bands,_",
        "_edge-vs-P&L regression, and the cost-drag reality check._",
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
