"""EDGAR companyfacts -> tidy fundamentals table (plan_value.md §1, step 2).

Downloads the nightly companyfacts.zip bulk file (~1.3GB, one JSON per
filer) and parses ONLY the universe's CIK members into a wide fundamentals
table: one row per (ticker, period_end, period_type) with a column per
concept from ingest/xbrl_tags.py.

Parsing rules:
  * annual flows: 10-K rows whose duration spans a fiscal year (330-380d);
    amended/restated values win via latest `filed` date per period-end;
  * annual instants: 10-K balance-sheet values at the same period ends;
  * quarterly flows: 10-Q rows with ~quarter duration (75-100d) — income
    items mostly; YTD-cumulative cash-flow rows are excluded by the filter;
  * a company missing any REQUIRED_CORE concept is DROPPED and logged with
    the concepts that failed (prefer dropping over guessing);
  * every (company, concept) -> winning tag is recorded for audit.

If drops exceed MAX_DROP_SHARE of the universe the run raises instead of
silently proceeding (plan: stop and show if >15% is affected).
"""

from __future__ import annotations

import json
import logging
import zipfile
from datetime import date, datetime

import pandas as pd

from common import config
from common.edgar import edgar_get, make_edgar_session
from ingest.xbrl_tags import CONCEPTS, REQUIRED_CORE

log = logging.getLogger("ete.edgar_facts")

COMPANYFACTS_URL = "https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip"
CIK_MAP_URL = "https://www.sec.gov/files/company_tickers.json"

MAX_DROP_SHARE = 0.15
FY_DURATION = (330, 380)   # days spanning an annual flow
Q_DURATION = (75, 100)     # days spanning a quarterly flow


# ------------------------------------------------------------- downloads ----
def download_cik_map(session=None) -> pd.DataFrame:
    session = session or make_edgar_session()
    resp = edgar_get(session, CIK_MAP_URL)
    if resp is None:
        raise RuntimeError("could not fetch SEC ticker->CIK map")
    config.EDGAR_DIR.mkdir(parents=True, exist_ok=True)
    config.CIK_MAP_JSON.write_text(resp.text)
    return parse_cik_map(resp.json())


def parse_cik_map(payload: dict) -> pd.DataFrame:
    rows = [
        {"ticker": v["ticker"].upper().replace(".", "-"), "cik": int(v["cik_str"]),
         "entity": v["title"]}
        for v in payload.values()
    ]
    return pd.DataFrame(rows).drop_duplicates("ticker").reset_index(drop=True)


def download_companyfacts(session=None, force: bool = False) -> None:
    """Stream the bulk zip to disk (skipped when a recent copy exists)."""
    if config.COMPANYFACTS_ZIP.exists() and not force:
        log.info("companyfacts.zip already on disk; skipping download")
        return
    session = session or make_edgar_session()
    log.info("downloading companyfacts.zip (~1.3GB) ...")
    resp = edgar_get(session, COMPANYFACTS_URL, stream=True, timeout=600, retries=2)
    if resp is None:
        raise RuntimeError("companyfacts.zip download failed")
    config.EDGAR_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.COMPANYFACTS_ZIP.with_suffix(".part")
    written = 0
    with tmp.open("wb") as fh:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            fh.write(chunk)
            written += len(chunk)
    tmp.rename(config.COMPANYFACTS_ZIP)
    log.info("companyfacts.zip: %.0f MB", written / 1e6)


# --------------------------------------------------------------- parsing ----
def _dur_days(entry: dict) -> int | None:
    try:
        start = date.fromisoformat(entry["start"])
        end = date.fromisoformat(entry["end"])
        return (end - start).days
    except (KeyError, ValueError, TypeError):
        return None


def _dedupe_latest_filed(entries: list[dict]) -> dict[str, float]:
    """{period_end -> value}, amendments resolved by latest `filed`."""
    best: dict[str, tuple[str, float]] = {}
    for e in entries:
        end, filed = e.get("end"), e.get("filed", "")
        if end is None or e.get("val") is None:
            continue
        if end not in best or filed > best[end][0]:
            best[end] = (filed, float(e["val"]))
    return {end: v for end, (_, v) in best.items()}


def _series_for_tag(units_entries: list[dict], kind: str, period: str) -> dict[str, float]:
    """Filter one tag's fact list down to {period_end: value} for FY or Q."""
    forms = ("10-K", "10-K/A") if period == "FY" else ("10-Q", "10-Q/A")
    keep = []
    for e in units_entries:
        if e.get("form") not in forms:
            continue
        if kind == "flow":
            d = _dur_days(e)
            lo, hi = FY_DURATION if period == "FY" else Q_DURATION
            if d is None or not (lo <= d <= hi):
                continue
        keep.append(e)
    return _dedupe_latest_filed(keep)


def resolve_concept(facts: dict, spec: dict, period: str) -> tuple[str | None, dict[str, float]]:
    """Merge candidate tags per-YEAR (higher priority wins on collisions).

    Filers switch tags mid-history (e.g. LongTermDebtNoncurrent stops, plain
    LongTermDebt continues) — taking only the first tag with data leaves
    holes, so lower-priority tags fill years the primary tag lacks.
    Returns (primary tag used, {period_end: value}).
    """
    ns = facts.get(spec.get("namespace", "us-gaap"), {})
    combined: dict[str, float] = {}
    primary = None
    for tag in reversed(spec["tags"]):  # lowest priority first; later overwrite
        node = ns.get(tag)
        if not node:
            continue
        entries = (node.get("units") or {}).get(spec["unit"], [])
        series = _series_for_tag(entries, spec["kind"], period)
        if series:
            combined.update(series)
            primary = tag  # ends at the highest-priority tag with data
    return primary, combined


def parse_company(payload: dict, ticker: str, years: int = config.FUNDAMENTAL_YEARS):
    """One filer JSON -> (annual_df, quarterly_df, tags_used, missing_core)."""
    facts = payload.get("facts", {})
    tags_used: dict[str, str] = {}
    annual: dict[str, dict[str, float]] = {}
    quarterly: dict[str, dict[str, float]] = {}

    for concept, spec in CONCEPTS.items():
        tag, series = resolve_concept(facts, spec, "FY")
        if tag:
            tags_used[concept] = tag
            annual[concept] = series
        if spec["kind"] == "flow":
            qtag, qseries = resolve_concept(facts, spec, "Q")
            if qtag:
                quarterly[concept] = qseries

    missing_core = [c for c in REQUIRED_CORE if c not in annual]
    if missing_core:
        return None, None, tags_used, missing_core

    # instants may be reported a day or two off the flow period end; align by
    # nearest instant within 10 days of each annual flow end.
    flow_ends = sorted(annual["revenue"].keys())[-(years + 1):]

    def nearest(series: dict[str, float], end: str) -> float:
        if end in series:
            return series[end]
        target = date.fromisoformat(end)
        best, best_gap = float("nan"), 11
        for k, v in series.items():
            gap = abs((date.fromisoformat(k) - target).days)
            if gap < best_gap:
                best, best_gap = v, gap
        return best

    rows = []
    for end in flow_ends:
        row = {"period_end": end, "period_type": "FY"}
        for concept in CONCEPTS:
            series = annual.get(concept, {})
            if not series:
                row[concept] = float("nan")
            elif CONCEPTS[concept]["kind"] == "instant":
                row[concept] = nearest(series, end)
            else:
                row[concept] = series.get(end, float("nan"))
        rows.append(row)
    annual_df = pd.DataFrame(rows)
    annual_df["ticker"] = ticker

    q_rows = []
    for concept, series in quarterly.items():
        for end, val in series.items():
            q_rows.append({"ticker": ticker, "period_end": end, "concept": concept, "value": val})
    q_long = pd.DataFrame(q_rows)
    quarterly_df = (
        q_long.pivot_table(index=["ticker", "period_end"], columns="concept", values="value")
        .reset_index()
        if len(q_rows)
        else pd.DataFrame(columns=["ticker", "period_end"])
    )
    quarterly_df["period_type"] = "Q"
    return annual_df, quarterly_df, tags_used, []


# ------------------------------------------------------------------ build ---
def build_fundamentals(universe: pd.DataFrame, zip_path=None):
    """Parse the bulk zip for every universe CIK -> (annual, quarterly)."""
    zip_path = zip_path or config.COMPANYFACTS_ZIP
    annual_frames, q_frames, drops, tag_rows = [], [], [], []
    with zipfile.ZipFile(zip_path) as zf:
        members = set(zf.namelist())
        for r in universe.itertuples(index=False):
            member = f"CIK{r.cik:010d}.json"
            if member not in members:
                drops.append({"ticker": r.ticker, "cik": r.cik, "reason": "no companyfacts entry"})
                continue
            try:
                payload = json.loads(zf.read(member))
            except (ValueError, KeyError) as exc:
                drops.append({"ticker": r.ticker, "cik": r.cik, "reason": f"unparseable JSON: {exc}"})
                continue
            adf, qdf, tags_used, missing = parse_company(payload, r.ticker)
            for concept, tag in tags_used.items():
                tag_rows.append({"ticker": r.ticker, "concept": concept, "tag": tag})
            if missing:
                drops.append(
                    {"ticker": r.ticker, "cik": r.cik,
                     "reason": f"unresolvable core concepts: {','.join(missing)}"}
                )
                continue
            if len(adf) < 4:
                drops.append(
                    {"ticker": r.ticker, "cik": r.cik,
                     "reason": f"only {len(adf)} annual periods"}
                )
                continue
            adf["cik"] = r.cik
            annual_frames.append(adf)
            if len(qdf):
                qdf["cik"] = r.cik
                q_frames.append(qdf)

    config.EDGAR_DIR.mkdir(parents=True, exist_ok=True)
    drops_df = pd.DataFrame(drops, columns=["ticker", "cik", "reason"])
    drops_df.to_csv(config.FUNDAMENTALS_DROPS_CSV, index=False)
    pd.DataFrame(tag_rows).to_csv(config.UNMAPPED_TAGS_CSV.with_name("tags_used.csv"), index=False)

    drop_share = len(drops_df) / max(len(universe), 1)
    log.info(
        "fundamentals: parsed %d companies, dropped %d (%.1f%%) -> %s",
        len(annual_frames), len(drops_df), 100 * drop_share, config.FUNDAMENTALS_DROPS_CSV,
    )
    if drop_share > MAX_DROP_SHARE:
        top = drops_df["reason"].value_counts().head(8).to_string()
        raise RuntimeError(
            f"XBRL mapping failed for {100 * drop_share:.0f}% of the universe "
            f"(> {100 * MAX_DROP_SHARE:.0f}% threshold). Plan says stop and show.\n"
            f"Top drop reasons:\n{top}"
        )

    annual = pd.concat(annual_frames, ignore_index=True) if annual_frames else pd.DataFrame()
    quarterly = pd.concat(q_frames, ignore_index=True) if q_frames else pd.DataFrame()
    return annual, quarterly, drops_df


def run(universe: pd.DataFrame | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    if universe is None:
        universe = pd.read_parquet(config.VALUE_UNIVERSE_PARQUET)
    session = make_edgar_session()
    download_companyfacts(session)
    annual, quarterly, _ = build_fundamentals(universe)
    combined = pd.concat([annual, quarterly], ignore_index=True)
    combined.to_parquet(config.FUNDAMENTALS_PARQUET, index=False)
    log.info(
        "fundamentals -> %s (%d annual rows, %d quarterly rows, %d names)",
        config.FUNDAMENTALS_PARQUET, len(annual), len(quarterly),
        annual["ticker"].nunique() if len(annual) else 0,
    )
    return combined


if __name__ == "__main__":
    config.setup_logging()
    run()
