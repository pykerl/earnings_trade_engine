"""One-page thesis memo generator (plan_value.md §5 — the core deliverable).

Data sections are fully automated from the quality/valuation/disqualifier
tables; filing-text sections pull the actual 10-K Item 1 / MD&A excerpts and
mark them [FOR HUMAN REVIEW] — the screen measures moat footprints, the
human judges the moat.

Memos are git-versioned Markdown in memos/, one dated file per generation,
never overwritten. Every memo also freezes a pre-registered expectations
row via journal/writer.py.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from datetime import date, datetime

import numpy as np
import pandas as pd
from jinja2 import Environment, FileSystemLoader

from common import config
from common.edgar import edgar_get, make_edgar_session
from features.disqualifiers import _cached_submissions

log = logging.getLogger("ete.memos")

DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
EXCERPT_CHARS = 1100


# ------------------------------------------------------- filing excerpts ----
def latest_10k_doc(submissions: dict) -> tuple[str, str] | None:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    for form, acc, doc in zip(
        recent.get("form", []), recent.get("accessionNumber", []),
        recent.get("primaryDocument", []),
    ):
        if str(form) == "10-K" and doc:
            return acc.replace("-", ""), doc
    return None


def _strip_html(text: str) -> str:
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html_lib.unescape(text)
    return re.sub(r"\s+", " ", text)


def extract_item(text: str, item: str, next_items: list[str]) -> str:
    """Text window from 'Item N.' to the next item heading (second occurrence
    preferred — the first is usually the table of contents)."""
    pat = re.compile(rf"item\s+{re.escape(item)}\.?\s", re.I)
    starts = [m.start() for m in pat.finditer(text)]
    if not starts:
        return ""
    start = starts[1] if len(starts) > 1 else starts[0]
    end = len(text)
    for nxt in next_items:
        m = re.search(rf"item\s+{re.escape(nxt)}\.?\s", text[start + 50:], re.I)
        if m:
            end = min(end, start + 50 + m.start())
    return text[start:end][:EXCERPT_CHARS].strip()


def fetch_10k_excerpts(cik: int, session) -> dict:
    out = {"business_excerpt": "", "mda_excerpt": ""}
    subs = _cached_submissions(cik, session)
    if not subs:
        return out
    doc = latest_10k_doc(subs)
    if not doc:
        return out
    acc, name = doc
    resp = edgar_get(session, DOC_URL.format(cik=cik, acc_nodash=acc, doc=name), retries=2, timeout=90)
    if resp is None:
        return out
    text = _strip_html(resp.text)
    out["business_excerpt"] = extract_item(text, "1", ["1A", "1B", "2"]) or "(Item 1 extraction failed — open the 10-K)"
    out["mda_excerpt"] = extract_item(text, "7", ["7A", "8"]) or "(MD&A extraction failed — open the 10-K)"
    return out


# ------------------------------------------------------------- templating ---
def thesis_driver(row: pd.Series) -> str:
    price_below_epv = row["market_cap"] < row["value_epv"]
    ig, hg = row.get("implied_growth", np.nan), row.get("rev_cagr_10y", np.nan)
    if price_below_epv:
        return (
            f"Price (${row['market_cap'] / 1e9:.1f}B) sits BELOW the zero-growth EPV "
            f"(${row['value_epv'] / 1e9:.1f}B): the market is paying nothing for growth in a "
            f"business that compounded revenue at {100 * hg:.1f}%/yr for a decade. If the moat "
            f"merely defends, the price is covered; any growth is free."
        )
    if np.isfinite(ig) and np.isfinite(hg) and ig < hg - 0.02:
        return (
            f"The market is pricing {100 * ig:.1f}%/yr growth for a decade; this business has "
            f"actually delivered {100 * hg:.1f}%/yr. The discount is a bet that the record "
            f"breaks — the burden of proof sits with the pessimists."
        )
    if row.get("gm_trend", 0) < -0.005:
        return (
            "Margins have compressed recently — the thesis requires mean reversion. Verify in "
            "the MD&A whether the compression is priced input costs (cyclical) or competition "
            "(structural) before trusting the valuation."
        )
    return (
        "No single loud driver: the discount looks like sector/sentiment sourness rather than "
        "a company-specific story. Confirm nothing idiosyncratic hides in the filings."
    )


def build_bear_case(row: pd.Series) -> list[str]:
    lines = []
    nd = row.get("nd_ebitda", np.nan)
    if np.isfinite(nd) and 2.0 <= nd <= 3.0:
        lines.append(f"Leverage crept up (ND/EBITDA {nd:.1f}, threshold 3.0) and a downturn made it bite.")
    if row.get("gm_trend", 0) < 0:
        lines.append("The margin compression wasn't cyclical — pricing power was already gone.")
    if row.get("rev_cagr_5y", np.nan) < row.get("rev_cagr_10y", np.nan):
        lines.append("Growth had already slowed (5-yr CAGR below 10-yr) and kept slowing — the reverse DCF bar was never met.")
    if row.get("sbc_fcf_10y", 0) > 0.10:
        lines.append(f"SBC ({100 * row['sbc_fcf_10y']:.0f}% of FCF) quietly diluted the per-share thesis.")
    if row.get("demote_reasons"):
        lines.append(f"The demotion flags were the tell: {row['demote_reasons']}.")
    lines.append("The maintenance-capex proxy understated true reinvestment needs; owner earnings were overstated.")
    lines.append("Substitution risk the screen cannot see (the load-bearing human-review item) materialized.")
    return lines


def build_expectations(row: pd.Series) -> list[str]:
    exp = []
    g = row.get("rev_cagr_5y", np.nan)
    if np.isfinite(g):
        exp.append(f"Next FY revenue growth within ±3pts of {100 * g:.1f}% (recent 5-yr pace)")
    gm, sig = row.get("gross_margin", np.nan), row.get("gm_sigma_10y", np.nan)
    if np.isfinite(gm) and np.isfinite(sig):
        exp.append(f"Gross margin stays inside {100 * (gm - 2 * sig):.0f}%–{100 * (gm + 2 * sig):.0f}% (±2σ of its 10-yr band)")
    if row.get("buyback_years_10y", 0) >= 8:
        exp.append("Buybacks continue (repurchased in 8+ of the last 10 years)")
    nd = row.get("nd_ebitda", np.nan)
    if np.isfinite(nd):
        exp.append(f"Net debt/EBITDA stays at or below {max(nd + 0.5, 1.0):.1f}")
    exp.append("FCF/NI conversion stays ≥ 0.8 — accruals do not diverge")
    return exp


def earnings_note(row: pd.Series, events: pd.DataFrame | None) -> str:
    if events is not None and len(events):
        hit = events[events["ticker"] == row["ticker"]]
        if len(hit):
            ev = hit.iloc[0]
            return (
                f"Reports {ev['earnings_date']} ({ev['session']}). One quarter can validate or "
                "wound the margin/accruals expectations below; it cannot prove or disprove a "
                "10-year owner-earnings record. This process never buys BECAUSE earnings are "
                "coming — a fearful post-print drop that widens the margin of safety is the "
                "only sense in which the date matters."
            )
    return (
        "No confirmed report date inside the 21-day calendar window. The thesis does not "
        "depend on the next print."
    )


def verdict_sentences(row: pd.Series) -> tuple[str, str]:
    mos = row.get("margin_of_safety", np.nan)
    roic = row.get("roic_median_10y", np.nan)
    v = row["verdict"]
    if v == "buy candidate":
        s1 = f"quality gates passed, {100 * mos:.0f}% below the most conservative lens."
        s2 = (
            f"a {100 * roic:.0f}%-ROIC business bought {100 * mos:.0f}% below a conservative "
            f"value should beat an index fund's ~10% expectancy without heroic assumptions — "
            f"if the human review confirms the moat is real."
        )
    elif v == "watch (needs price)":
        s1 = f"quality passes but {100 * mos:.0f}% margin of safety is below the {100 * config.MOS_BUY:.0f}% bar."
        s2 = "at today's price the index fund wins; pre-set the entry level and wait."
    else:
        s1 = "does not clear the gates."
        s2 = "the index fund wins by default."
    return s1, s2


def render_memo(
    row: pd.Series,
    excerpts: dict,
    insider_line: str,
    guru_line: str,
    events: pd.DataFrame | None,
    memo_date: date,
) -> str:
    env = Environment(loader=FileSystemLoader(config.MEMOS_DIR), autoescape=False)
    template = env.get_template("template.md.j2")
    near = row.get("demote_reasons") or "none fired"
    s1, s2 = verdict_sentences(row)
    return template.render(
        memo_date=memo_date.isoformat(),
        insider_line=insider_line,
        guru_line=guru_line,
        thesis=thesis_driver(row),
        bear_case=build_bear_case(row),
        near_misses=near,
        expectations=build_expectations(row),
        earnings_note=earnings_note(row, events),
        verdict_sentence=s1,
        index_fund_sentence=s2,
        **excerpts,
        **{k: row[k] for k in row.index if k not in ("verdict",)},
        verdict=row["verdict"],
    )


def write_memo(ticker: str, content: str, memo_date: date) -> str:
    """Dated file, never overwritten — same-day regeneration gets a suffix."""
    config.MEMOS_DIR.mkdir(parents=True, exist_ok=True)
    path = config.MEMOS_DIR / f"{ticker}_{memo_date}.md"
    if path.exists():
        stamp = datetime.now().strftime("%H%M%S")
        path = config.MEMOS_DIR / f"{ticker}_{memo_date}_{stamp}.md"
    path.write_text(content)
    return str(path)


def generate_memos(
    valuations: pd.DataFrame,
    universe: pd.DataFrame,
    insiders: pd.DataFrame | None,
    gurus: pd.DataFrame | None,
    events: pd.DataFrame | None,
    top_n: int = 15,
    session=None,
    memo_date: date | None = None,
) -> list[str]:
    memo_date = memo_date or date.today()
    session = session or make_edgar_session()
    cik_by_ticker = dict(zip(universe["ticker"], universe["cik"]))
    name_by_ticker = dict(zip(universe["ticker"], universe["name"]))
    top = valuations[valuations["rank_score"] > 0].head(top_n)
    paths = []
    for _, row in top.iterrows():
        t = row["ticker"]
        row = row.copy()
        row["name"] = name_by_ticker.get(t, t)
        ins_line = "not scanned"
        if insiders is not None and t in set(insiders["ticker"]):
            i = insiders.set_index("ticker").loc[t]
            ins_line = (
                f"{int(i['buys_12m'])} open-market buys (${i['buy_dollars'] / 1e6:.1f}M) vs "
                f"{int(i['sells_12m'])} sells; {int(i['distinct_buyers'])} distinct buyers"
                + (" — CLUSTER BUY" if i["cluster_buy"] else "")
            )
        g_line = "no configured holder owns it"
        if gurus is not None and len(gurus) and t in set(gurus["ticker"]):
            gg = gurus[gurus["ticker"] == t]
            g_line = "; ".join(
                f"{r.holder}: ${r.value_kusd / 1e6:.2f}B" for r in gg.itertuples(index=False)
            )
        excerpts = fetch_10k_excerpts(int(cik_by_ticker[t]), session) if t in cik_by_ticker else {
            "business_excerpt": "", "mda_excerpt": ""
        }
        content = render_memo(row, excerpts, ins_line, g_line, events, memo_date)
        paths.append(write_memo(t, content, memo_date))
    log.info("wrote %d memos -> %s", len(paths), config.MEMOS_DIR)
    return paths
