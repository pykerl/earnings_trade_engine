"""Engine-signal columns for the picks holdings tables (plan §2 Panel 2).

Three columns, three disciplines:
  * value verdict — the value engine's gate outcome (verdict, moat flag,
    margin of safety), computed ONCE per ticker and cached first-write-wins
    in data/picks_value_verdicts.parquet so mid-season restatements can't
    quietly rewrite what the framework said at inception;
  * crowding — Reddit mention-velocity z-score, refreshed every run;
  * earnings edge — implied vs fair move once a name enters the options
    engine's window, refreshed every run, falling back to the frozen T-1
    journal row for names the main engine doesn't cover.

Every column degrades to "n/a" (with a reason) when a sibling engine's
output file is absent — the tab must render regardless.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.picks_enrich")

VALUE_CACHE = config.DATA_DIR / "picks_value_verdicts.parquet"
ENRICHED_PARQUET = config.DATA_DIR / "picks_enriched.parquet"

NA = "n/a"


def _fmt_mos(mos: float) -> str:
    if not np.isfinite(mos):
        return ""
    return " · MoS <-999%" if mos < -9.99 else f" · MoS {mos:+.0%}"


def _fresh_verdicts(tickers: list[str]) -> pd.DataFrame:
    """Resolve verdict strings from the value engine's outputs, if present."""
    if not config.VALUATIONS_PARQUET.exists():
        log.warning("valuations.parquet absent — value verdicts degrade to %s", NA)
        return pd.DataFrame(columns=["ticker", "value_verdict"])
    v = pd.read_parquet(config.VALUATIONS_PARQUET).set_index("ticker")
    demotes = pd.Series(dtype=str)
    if config.DISQUALIFIERS_PARQUET.exists():
        d = pd.read_parquet(config.DISQUALIFIERS_PARQUET)
        demotes = d.set_index("ticker")["demote_reasons"].fillna("")
    rows = []
    for t in tickers:
        if t not in v.index:
            rows.append({"ticker": t, "value_verdict": f"{NA} (outside value universe)"})
            continue
        r = v.loc[t]
        s = str(r["verdict"])
        if bool(r.get("moat_flag", False)):
            s += " · moat"
        s += _fmt_mos(float(r.get("margin_of_safety", np.nan)))
        flags = str(demotes.get(t, "")).strip(";")
        if flags:
            s += f" · flags: {flags}"
        rows.append({"ticker": t, "value_verdict": s})
    return pd.DataFrame(rows)


def value_verdicts(tickers: list[str]) -> pd.DataFrame:
    """Cached once per ticker; only never-seen tickers are resolved fresh.

    A ticker whose verdict could not be resolved (sibling file missing) is
    NOT cached, so a later run with the file present can still fill it in —
    but once written, a row is never recomputed.
    """
    cached = (
        pd.read_parquet(VALUE_CACHE)
        if VALUE_CACHE.exists()
        else pd.DataFrame(columns=["ticker", "value_verdict"])
    )
    todo = [t for t in tickers if t not in set(cached["ticker"])]
    if todo:
        fresh = _fresh_verdicts(todo)
        if len(fresh):
            cached = pd.concat([cached, fresh], ignore_index=True)
            cached.to_parquet(VALUE_CACHE, index=False)
            log.info("value verdicts cached for %s", ", ".join(fresh["ticker"]))
    out = pd.DataFrame({"ticker": tickers}).merge(cached, on="ticker", how="left")
    out["value_verdict"] = out["value_verdict"].fillna(f"{NA} (valuations not built)")
    return out


def crowding(tickers: list[str]) -> pd.DataFrame:
    cols = ["ticker", "crowding", "velocity_z", "mentions"]
    base = pd.DataFrame({"ticker": tickers})
    path = config.DATA_DIR / "mentions_latest.parquet"
    if not path.exists():
        log.warning("mentions_latest.parquet absent — crowding degrades to %s", NA)
        base["crowding"] = f"{NA} (mentions not built)"
        return base.reindex(columns=cols)
    m = pd.read_parquet(path)[["ticker", "mentions", "velocity_z"]]
    out = base.merge(m, on="ticker", how="left")
    out["crowding"] = [
        f"z {z:+.1f} · {int(n)} mentions" if np.isfinite(z) else f"{NA} (not trending)"
        for z, n in zip(out["velocity_z"].fillna(np.nan), out["mentions"].fillna(0))
    ]
    return out.reindex(columns=cols)


def earnings_edge(tickers: list[str]) -> pd.DataFrame:
    """Implied vs fair from the live engine, else from the frozen T-1 row."""
    from picks.events import PICKS_PREDICTIONS_CSV

    cols = ["ticker", "earnings_edge", "implied_move_mid", "fair_move", "edge"]
    frames = []
    if config.SCORED_PARQUET.exists():
        s = pd.read_parquet(config.SCORED_PARQUET)
        frames.append(s[["ticker", "implied_move_mid", "fair_move"]].assign(src="live"))
    if PICKS_PREDICTIONS_CSV.exists():
        j = pd.read_csv(PICKS_PREDICTIONS_CSV)
        frames.append(j[["ticker", "implied_move_mid", "fair_move"]].assign(src="T-1 frozen"))
    base = pd.DataFrame({"ticker": tickers})
    if not frames:
        base["earnings_edge"] = f"{NA} (not in window)"
        return base.reindex(columns=cols)
    pool = pd.concat(frames, ignore_index=True).drop_duplicates("ticker", keep="first")
    out = base.merge(pool, on="ticker", how="left")
    out["edge"] = out["implied_move_mid"] / out["fair_move"] - 1.0
    labels = []
    for r in out.itertuples(index=False):
        if not np.isfinite(getattr(r, "implied_move_mid", np.nan) or np.nan):
            labels.append(f"{NA} (not in window)")
        elif np.isfinite(r.edge):
            side = "rich" if r.edge > 0.15 else ("cheap" if r.edge < -0.15 else "fair")
            labels.append(
                f"impl {r.implied_move_mid:.1%} vs fair {r.fair_move:.1%} ({side}, {r.src})"
            )
        else:
            labels.append(f"impl {r.implied_move_mid:.1%} · fair {NA} ({r.src})")
    out["earnings_edge"] = labels
    return out.reindex(columns=cols)


def run(tickers: list[str] | None = None) -> pd.DataFrame:
    from picks.nav import load_rules

    config.ensure_dirs()
    if tickers is None:
        rules = load_rules()
        tickers = [t for p in rules["portfolios"].values() for t in p["tickers"]]
    enriched = (
        value_verdicts(tickers)
        .merge(crowding(tickers), on="ticker")
        .merge(earnings_edge(tickers), on="ticker")
    )
    enriched.to_parquet(ENRICHED_PARQUET, index=False)
    log.info("picks enrichment written for %d names -> %s", len(enriched), ENRICHED_PARQUET)
    return enriched


if __name__ == "__main__":
    config.setup_logging()
    print(run().to_string(index=False))
