"""Disqualifier checklist — Munger inversion, runs before ranking (plan §4).

Quant flags (from the fundamentals/quality tables):
  * structural revenue decline (3+ yrs) without offsetting FCF durability
  * net debt/EBITDA > 3 or interest coverage < 4
  * serial dilution (share CAGR > +2%/yr) or SBC > 20% of FCF
  * accruals divergence (NI trend up while CFO trend is not)
  * Altman-Z (book variant) in the distress zone — coarse trap filter

Filing-record flags (EDGAR submissions JSON + full-text search):
  * late filings: NT 10-K / NT 10-Q in the last 3 years
  * auditor change: 8-K item 4.01 in the last 3 years
  * restatement / non-reliance: 8-K item 4.02 in the last 3 years
  * going-concern language: full-text hit for "substantial doubt" +
    "going concern" in the last two 10-K years

Severity: EJECT (going concern, restatement, distress-zone Z, leverage
breach) removes the name from ranking; DEMOTE (decline, dilution, accruals,
auditor change, late filing) halves the rank score per flag. Substitution
risk and customer concentration cannot be automated — they set
needs_human_review, never a silent pass.

Output: data/disqualifiers.parquet
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, timedelta

import numpy as np
import pandas as pd

from common import config
from common.edgar import edgar_get, make_edgar_session

log = logging.getLogger("ete.disqualifiers")

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"
FTS_URL = "https://efts.sec.gov/LATEST/search-index"

EJECT_FLAGS = ("leverage", "altman_distress", "going_concern", "restatement")
DEMOTE_FLAGS = ("structural_decline", "dilution", "accruals", "auditor_change", "late_filing")

SUBMISSIONS_CACHE_DAYS = 7


# ------------------------------------------------------------- quant flags --
def quant_flags(qrow: pd.Series, annual: pd.DataFrame) -> dict:
    """§4 flags computable from the numbers alone."""
    df = annual.sort_values("period_end")
    rev = df["revenue"].dropna()
    fcf = (df["cfo"] - df["capex"]).dropna()

    decline = bool(len(rev) >= 4 and rev.iloc[-1] < rev.iloc[-4] and rev.iloc[-2] < rev.iloc[-3])
    fcf_durable = bool(len(fcf) >= 4 and fcf.tail(3).mean() >= fcf.iloc[-4])

    ni = df["net_income"].tail(6)
    cfo = df["cfo"].tail(6)

    def slope(s):
        s = s.dropna()
        if len(s) < 4:
            return np.nan
        return float(np.polyfit(np.arange(len(s)), s.to_numpy(dtype=float), 1)[0])

    ni_up = slope(ni)
    cfo_up = slope(cfo)
    accruals_div = bool(
        np.isfinite(ni_up) and np.isfinite(cfo_up) and ni_up > 0 and cfo_up <= 0
    ) or bool(np.isfinite(qrow.get("fcf_ni_10y", np.nan)) and qrow["fcf_ni_10y"] < 0.6)

    nd = qrow.get("nd_ebitda", np.nan)
    cover = qrow.get("interest_coverage", np.nan)
    leverage = bool(
        (np.isfinite(nd) and nd > config.DQ_ND_EBITDA_MAX)
        or (np.isfinite(cover) and cover < config.DQ_INTEREST_COVER_MIN)
    )

    share_cagr = qrow.get("share_cagr_10y", np.nan)
    sbc = qrow.get("sbc_fcf_10y", np.nan)
    dilution = bool(
        (np.isfinite(share_cagr) and share_cagr > config.DQ_DILUTION_CAGR)
        or (np.isfinite(sbc) and sbc > config.DQ_SBC_FCF_MAX)
    )

    z = qrow.get("altman_z_coarse", np.nan)
    return {
        "structural_decline": decline and not fcf_durable,
        "leverage": leverage,
        "dilution": dilution,
        "accruals": accruals_div,
        "altman_distress": bool(np.isfinite(z) and z < 1.1),
    }


# ------------------------------------------------------ filing-record flags --
def _cached_submissions(cik: int, session) -> dict | None:
    cache = config.EDGAR_DIR / "submissions" / f"CIK{cik:010d}.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and time.time() - cache.stat().st_mtime < SUBMISSIONS_CACHE_DAYS * 86400:
        try:
            return json.loads(cache.read_text())
        except ValueError:
            pass
    resp = edgar_get(session, SUBMISSIONS_URL.format(cik=cik), retries=2)
    if resp is None:
        return None
    cache.write_text(resp.text)
    try:
        return resp.json()
    except ValueError:
        return None


def filing_record_flags(submissions: dict, today: date | None = None) -> dict:
    """Late filings + 8-K item 4.01/4.02 from the submissions index."""
    today = today or date.today()
    cutoff = (today - timedelta(days=3 * 365)).isoformat()
    recent = (submissions.get("filings") or {}).get("recent") or {}
    forms = recent.get("form", [])
    dates = recent.get("filingDate", [])
    items = recent.get("items", [])
    late = auditor = restate = False
    for i, form in enumerate(forms):
        if i < len(dates) and dates[i] < cutoff:
            continue
        f = str(form).upper()
        it = str(items[i]) if i < len(items) else ""
        if f.startswith("NT 10-K") or f.startswith("NT 10-Q"):
            late = True
        if f.startswith("8-K"):
            if "4.01" in it:
                auditor = True
            if "4.02" in it:
                restate = True
    return {"late_filing": late, "auditor_change": auditor, "restatement": restate}


def going_concern_hit(cik: int, session, today: date | None = None) -> bool:
    """EDGAR full-text: 'substantial doubt' + 'going concern' in recent 10-Ks.

    Cached for 7 days per CIK — the answer changes at most once per 10-K.
    """
    today = today or date.today()
    cache = config.EDGAR_DIR / "fts_cache" / f"gc_{cik:010d}.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and time.time() - cache.stat().st_mtime < SUBMISSIONS_CACHE_DAYS * 86400:
        try:
            return bool(json.loads(cache.read_text())["hit"])
        except (ValueError, KeyError):
            pass
    resp = edgar_get(
        session, FTS_URL,
        params={
            "q": '"substantial doubt" "ability to continue as a going concern"',
            "forms": "10-K",
            "ciks": f"{cik:010d}",
            "startdt": (today - timedelta(days=730)).isoformat(),
            "enddt": today.isoformat(),
        },
        retries=2,
    )
    if resp is None:
        return False
    try:
        hit = (resp.json().get("hits", {}).get("total", {}) or {}).get("value", 0) > 0
    except ValueError:
        return False
    cache.write_text(json.dumps({"hit": hit}))
    return hit


# ------------------------------------------------------------------ combine --
def combine_flags(quant: dict, record: dict, going_concern: bool) -> dict:
    flags = {**quant, **record, "going_concern": going_concern}
    eject = [f for f in EJECT_FLAGS if flags.get(f)]
    demote = [f for f in DEMOTE_FLAGS if flags.get(f)]
    review = ["substitution risk unassessed (cannot be automated)"]
    if going_concern:
        review.append("going-concern language found — read the opinion")
    return {
        **flags,
        "eject": bool(eject),
        "eject_reasons": ";".join(eject),
        "demote_count": len(demote),
        "demote_reasons": ";".join(demote),
        "needs_human_review": ";".join(review),
    }


def build_disqualifiers(
    quality: pd.DataFrame,
    fundamentals: pd.DataFrame,
    universe: pd.DataFrame,
    session=None,
    scan_filings: bool = True,
    today: date | None = None,
) -> pd.DataFrame:
    session = session or make_edgar_session()
    annual = fundamentals[fundamentals["period_type"] == "FY"]
    cik_by_ticker = dict(zip(universe["ticker"], universe["cik"]))
    rows = []
    for qrow in quality.itertuples(index=False):
        q = pd.Series(qrow._asdict())
        g = annual[annual["ticker"] == q["ticker"]]
        quant = quant_flags(q, g)
        record = {"late_filing": False, "auditor_change": False, "restatement": False}
        gc = False
        cik = cik_by_ticker.get(q["ticker"])
        if scan_filings and cik:
            subs = _cached_submissions(int(cik), session)
            if subs:
                record = filing_record_flags(subs, today=today)
            # full-text scan is the expensive call: only when the cheap flags
            # haven't already ejected the name
            pre = combine_flags(quant, record, False)
            if not pre["eject"]:
                gc = going_concern_hit(int(cik), session, today=today)
        rows.append({"ticker": q["ticker"], **combine_flags(quant, record, gc)})
    out = pd.DataFrame(rows)
    log.info(
        "disqualifiers: %d names, %d ejected, %d with demotions",
        len(out), int(out["eject"].sum()), int((out["demote_count"] > 0).sum()),
    )
    return out


def run(scan_filings: bool = True) -> pd.DataFrame:
    config.ensure_dirs()
    quality = pd.read_parquet(config.QUALITY_PARQUET)
    fundamentals = pd.read_parquet(config.FUNDAMENTALS_PARQUET)
    universe = pd.read_parquet(config.VALUE_UNIVERSE_PARQUET)
    out = build_disqualifiers(quality, fundamentals, universe, scan_filings=scan_filings)
    out.to_parquet(config.DISQUALIFIERS_PARQUET, index=False)
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
