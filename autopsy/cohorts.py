"""Stage A — cohort autopsy: was the 76% skill? (plan_reddit_growth §2)

Reconstructs each WSB cohort as an equal-weight, buy-and-hold portfolio from
its publication date and answers, with numbers:

  * total return vs SPY and QQQ, max drawdown, hit rate;
  * contribution concentration — was it 2 winners carrying 8 losers?
  * entry-lag sensitivity (buy 0/1wk/1mo/3mo after publication) — how much
    of the move is gone by the time the crowd publishes;
  * factor decomposition — regress daily cohort excess returns on the free
    Fama-French market + momentum factors; the alpha left over is the only
    number that can be called stock-picking skill.

Output: reports/cohort_autopsy.md. Runs BEFORE any idea generation — this
calibrates whether Reddit belongs in the funnel at all.
"""

from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, timedelta

import numpy as np
import pandas as pd
import yaml

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.autopsy")

COHORTS_YAML = config.REPO_ROOT / "config" / "cohorts.yaml"
REPORTS_DIR = config.REPO_ROOT / "reports"

FF_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
FF_FACTORS_ZIP = FF_BASE + "F-F_Research_Data_Factors_daily_CSV.zip"
FF_MOM_ZIP = FF_BASE + "F-F_Momentum_Factor_daily_CSV.zip"


def load_cohorts(path=COHORTS_YAML) -> dict:
    return yaml.safe_load(path.read_text())


# ------------------------------------------------------------- price maths --
def ew_curve(prices: pd.DataFrame, tickers: list[str], entry: date) -> pd.Series | None:
    """Equal-weight buy-and-hold portfolio value (1.0 at entry close)."""
    cols = [t for t in tickers if t in prices.columns]
    if not cols:
        return None
    px = prices[cols].dropna(how="all")
    idx = px.index[px.index >= pd.Timestamp(entry)]
    if len(idx) < 2:
        return None
    base = px.loc[idx[0]]
    rel = px.loc[idx[0]:].div(base)
    return rel.mean(axis=1, skipna=True).rename("ew")


def total_return(curve: pd.Series) -> float:
    return float(curve.iloc[-1] / curve.iloc[0] - 1)


def max_drawdown(curve: pd.Series) -> float:
    running = curve.cummax()
    return float((curve / running - 1).min())


def per_name_returns(prices: pd.DataFrame, tickers: list[str], entry: date) -> pd.Series:
    out = {}
    for t in tickers:
        if t not in prices.columns:
            out[t] = np.nan
            continue
        s = prices[t].dropna()
        s = s[s.index >= pd.Timestamp(entry)]
        out[t] = float(s.iloc[-1] / s.iloc[0] - 1) if len(s) >= 2 else np.nan
    return pd.Series(out)


def contribution_concentration(name_returns: pd.Series) -> dict:
    """EW contributions = r_i / n. Top-2 share of the summed contribution."""
    contrib = name_returns.dropna() / len(name_returns.dropna())
    total = contrib.sum()
    top2 = contrib.sort_values(ascending=False).head(2)
    return {
        "portfolio_return": float(total),
        "top2_names": list(top2.index),
        "top2_contribution": float(top2.sum()),
        "top2_share": float(top2.sum() / total) if total > 0 else np.nan,
        "hit_rate": float((name_returns.dropna() > 0).mean()),
    }


# ------------------------------------------------------- Fama-French factors --
def parse_ff_csv(text: str) -> pd.DataFrame:
    """Ken French daily CSV: skip prose, keep yyyymmdd rows, values in %.

    Quirks handled: prose lines that contain commas, trailing commas on the
    header (",Mom,,") and on data rows ("20260529,-1.68,"), and the -99.99
    missing-value sentinel.
    """
    rows = []
    header: list[str] | None = None
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if header is None and len(parts) > 1 and parts[0] == "" and any(parts[1:]):
            header = [p.replace(" ", "") for p in parts[1:] if p]
            continue
        if header and parts[0].isdigit() and len(parts[0]) == 8:
            vals, ok = [], True
            for x in parts[1:1 + len(header)]:
                try:
                    v = float(x)
                except ValueError:
                    ok = False
                    break
                vals.append(v if v > -90 else float("nan"))
            if ok and len(vals) == len(header):
                rows.append([pd.Timestamp(parts[0])] + vals)
    df = pd.DataFrame(rows, columns=["date"] + header).set_index("date")
    return df / 100.0  # percent -> decimal


def fetch_ff_factors(session=None) -> pd.DataFrame | None:
    session = session or make_session()
    frames = []
    for url in (FF_FACTORS_ZIP, FF_MOM_ZIP):
        resp = get_with_retries(session, url, timeout=60)
        if resp is None:
            log.warning("Fama-French file unreachable: %s", url)
            return None
        with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
            text = zf.read(zf.namelist()[0]).decode("latin-1")
        frames.append(parse_ff_csv(text))
    ff = frames[0].join(frames[1], how="inner")
    ff.columns = [c.upper().replace("-", "_") for c in ff.columns]
    return ff


def factor_decomposition(curve: pd.Series, ff: pd.DataFrame) -> dict | None:
    """OLS of daily excess cohort returns on MKT_RF and MOM."""
    rets = curve.pct_change().dropna()
    rets.index = rets.index.tz_localize(None).normalize()
    joined = pd.concat([rets.rename("port"), ff], axis=1, join="inner").dropna()
    if len(joined) < 40:
        return None
    y = (joined["port"] - joined["RF"]).to_numpy()
    X = np.column_stack([
        np.ones(len(joined)),
        joined["MKT_RF"].to_numpy(),
        joined["MOM"].to_numpy(),
    ])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    r2 = 1 - resid.var() / y.var() if y.var() > 0 else np.nan
    return {
        "alpha_daily": float(beta[0]),
        "alpha_annualized": float((1 + beta[0]) ** 252 - 1),
        "beta_market": float(beta[1]),
        "beta_momentum": float(beta[2]),
        "r2": float(r2),
        "n_days": int(len(joined)),
        "window_end": str(joined.index[-1].date()),
    }


# ------------------------------------------------------------------ report --
def analyze_cohort(name: str, cohort: dict, prices: pd.DataFrame,
                   benchmarks: list[str], lags: list[int], ff: pd.DataFrame | None) -> dict:
    pub = date.fromisoformat(str(cohort["publication_date"]))
    tickers = cohort["tickers"]
    curve = ew_curve(prices, tickers, pub)
    if curve is None:
        return {"name": name, "error": "no price data"}
    names = per_name_returns(prices, tickers, pub)
    conc = contribution_concentration(names)
    bench = {
        b: total_return(ew_curve(prices, [b], pub)) for b in benchmarks
        if ew_curve(prices, [b], pub) is not None
    }
    lag_rows = {}
    for lag in lags:
        entry = pub + timedelta(days=lag)
        c = ew_curve(prices, tickers, entry)
        lag_rows[lag] = {
            "cohort": total_return(c) if c is not None else np.nan,
            **{b: (total_return(ew_curve(prices, [b], entry))
                   if ew_curve(prices, [b], entry) is not None else np.nan)
               for b in benchmarks},
        }
    return {
        "name": name,
        "description": cohort.get("description", ""),
        "publication_date": str(pub),
        "verified": bool(cohort.get("constituents_verified", False)),
        "verification_note": cohort.get("verification_note", ""),
        "tickers": tickers,
        "total_return": total_return(curve),
        "max_drawdown": max_drawdown(curve),
        "benchmarks": bench,
        "per_name": names.to_dict(),
        **conc,
        "entry_lags": lag_rows,
        "factors": factor_decomposition(curve, ff) if ff is not None else None,
    }


def render_report(results: list[dict], today: date) -> str:
    L = [
        f"# WSB cohort autopsy — Stage A ({today})",
        "",
        "Was the crowd's return skill, beta, or momentum? Equal-weight buy-and-hold",
        "from publication date, adjusted closes (yfinance), Fama-French daily factors.",
        "**This calibrates the funnel; it is not a buy list.**",
        "",
    ]
    for r in results:
        if r.get("error"):
            L += [f"## {r['name']} — ERROR: {r['error']}", ""]
            continue
        L += [f"## {r['name']} — {r['description']}", ""]
        if not r["verified"]:
            L += [f"> ⚠️ **PARTIAL COHORT — constituents unverified.** {r['verification_note'].strip()}", ""]
        L += [
            f"- Published: {r['publication_date']} · names: {', '.join(r['tickers'])}",
            f"- **Total return since publication: {100 * r['total_return']:.1f}%**"
            + "".join(f" · {b}: {100 * v:.1f}%" for b, v in r["benchmarks"].items()),
            f"- Max drawdown: {100 * r['max_drawdown']:.1f}% · hit rate: {100 * r['hit_rate']:.0f}% of names positive",
            f"- Contribution concentration: top 2 ({', '.join(r['top2_names'])}) supplied "
            f"{100 * r['top2_contribution']:.1f}pts of the {100 * r['portfolio_return']:.1f}% EW return"
            + (f" ({100 * r['top2_share']:.0f}% of it)" if np.isfinite(r["top2_share"]) else ""),
            "",
            "### Per-name returns since publication",
            "",
            "| Ticker | Return |",
            "|---|---|",
        ]
        for t, v in sorted(r["per_name"].items(), key=lambda kv: -(kv[1] if np.isfinite(kv[1]) else -9)):
            L.append(f"| {t} | {100 * v:.1f}% |" if np.isfinite(v) else f"| {t} | n/a |")
        L += ["", "### Entry-lag sensitivity (buy N days after publication)", "",
              "| Lag | Cohort | " + " | ".join(r["benchmarks"].keys()) + " |",
              "|---|---|" + "---|" * len(r["benchmarks"])]
        for lag, row in r["entry_lags"].items():
            cells = " | ".join(
                f"{100 * row[k]:.1f}%" if np.isfinite(row[k]) else "n/a"
                for k in ["cohort", *r["benchmarks"].keys()]
            )
            L.append(f"| {lag}d | {cells} |")
        f = r.get("factors")
        L += ["", "### Factor decomposition (daily, Mkt-RF + Momentum)", ""]
        if f:
            L += [
                f"- Window: {f['n_days']} trading days, factor data through {f['window_end']}",
                f"- Market beta: **{f['beta_market']:.2f}** · momentum beta: **{f['beta_momentum']:.2f}** · R²: {f['r2']:.2f}",
                f"- **Residual alpha: {100 * f['alpha_annualized']:.1f}%/yr** — the only number that can be called picking skill",
            ]
        else:
            L.append("- factor data unavailable for this window")
        L.append("")
    L += [
        "## Reading guide",
        "",
        "- A high market/momentum beta with near-zero residual alpha means the cohort's",
        "  return was the tape, not the picks — use Reddit as a THEME scout only.",
        "- Entry-lag decay measures how much is gone by the time the list is public;",
        "  it directly calibrates how to treat live mention spikes.",
        "- The 2025 row is a partial, press-attested cohort until the original thread",
        "  list is supplied — treat its numbers as indicative, not evidential.",
    ]
    return "\n".join(L)


def run(today: date | None = None) -> str:
    from common.yf_compat import patch_yfinance_tls

    patch_yfinance_tls()
    import yfinance as yf

    today = today or date.today()
    cfg = load_cohorts()
    cohorts, benchmarks = cfg["cohorts"], cfg["benchmarks"]
    lags = cfg.get("entry_lags_days", [0, 7, 30, 90])

    all_tickers = sorted({t for c in cohorts.values() for t in c["tickers"]} | set(benchmarks))
    earliest = min(date.fromisoformat(str(c["publication_date"])) for c in cohorts.values())
    log.info("autopsy: downloading %d tickers from %s", len(all_tickers), earliest)
    raw = yf.download(all_tickers, start=(earliest - timedelta(days=10)).isoformat(),
                      auto_adjust=True, progress=False)
    prices = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]]
    ff = fetch_ff_factors()

    results = [
        analyze_cohort(name, c, prices, benchmarks, lags, ff) for name, c in cohorts.items()
    ]
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = render_report(results, today)
    out = REPORTS_DIR / "cohort_autopsy.md"
    out.write_text(report)
    log.info("autopsy report -> %s", out)
    return str(out)


if __name__ == "__main__":
    config.setup_logging()
    run()
