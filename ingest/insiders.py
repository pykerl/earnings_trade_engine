"""Form 4 insider transactions -> trailing-12m cluster-buying signal (plan §1).

For each requested ticker (top candidates only — every Form 4 is one
rate-limited fetch): list Form 4 accessions from the cached submissions
index, pull each ownership XML (capped at MAX_FORMS_PER_NAME, newest
first), and count open-market purchases (transaction code P) vs sales (S).

Cluster-buy signal: >= 3 distinct insiders bought in the trailing 12 months
and gross buy dollars exceed sell dollars. Positions, not proof — the memo
cites it as capital-allocation evidence, nothing more.

Output: data/insiders.parquet
"""

from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from xml.etree import ElementTree

import pandas as pd

from common import config
from common.edgar import edgar_get, make_edgar_session
from features.disqualifiers import _cached_submissions

log = logging.getLogger("ete.insiders")

DOC_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"
MAX_FORMS_PER_NAME = 25

INSIDER_COLUMNS = [
    "ticker", "buys_12m", "sells_12m", "buy_dollars", "sell_dollars",
    "distinct_buyers", "cluster_buy",
]


def _form4_docs(submissions: dict, since: str) -> list[tuple[str, str]]:
    """[(accession_nodash, primary_document)] for Form 4 filings since date."""
    recent = (submissions.get("filings") or {}).get("recent") or {}
    out = []
    for form, filed, acc, doc in zip(
        recent.get("form", []), recent.get("filingDate", []),
        recent.get("accessionNumber", []), recent.get("primaryDocument", []),
    ):
        if str(form) == "4" and filed >= since and doc:
            # styled viewer paths (xslF345X05/foo.xml) wrap the raw XML name
            raw = doc.split("/")[-1]
            out.append((acc.replace("-", ""), raw))
    return out[:MAX_FORMS_PER_NAME]


def parse_form4(xml_text: str) -> list[dict]:
    """Non-derivative open-market transactions: code, shares, price, owner."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return []
    owner = root.findtext(".//reportingOwner/reportingOwnerId/rptOwnerName") or "unknown"
    rows = []
    for txn in root.findall(".//nonDerivativeTransaction"):
        code = txn.findtext(".//transactionCoding/transactionCode") or ""
        if code not in ("P", "S"):
            continue
        shares = float(txn.findtext(".//transactionShares/value") or 0)
        price = float(txn.findtext(".//transactionPricePerShare/value") or 0)
        rows.append({"owner": owner, "code": code, "dollars": shares * price})
    return rows


def scan_ticker(ticker: str, cik: int, session, today: date | None = None) -> dict:
    today = today or date.today()
    since = (today - timedelta(days=365)).isoformat()
    subs = _cached_submissions(cik, session)
    row = {c: 0 for c in INSIDER_COLUMNS if c != "ticker"}
    row["ticker"] = ticker
    row["cluster_buy"] = False
    if not subs:
        return row
    buyers = set()
    for acc, doc in _form4_docs(subs, since):
        resp = edgar_get(session, DOC_URL.format(cik=cik, acc_nodash=acc, doc=doc), retries=1)
        if resp is None:
            continue
        for txn in parse_form4(resp.text):
            if txn["code"] == "P":
                row["buys_12m"] += 1
                row["buy_dollars"] += txn["dollars"]
                buyers.add(txn["owner"])
            else:
                row["sells_12m"] += 1
                row["sell_dollars"] += txn["dollars"]
    row["distinct_buyers"] = len(buyers)
    row["cluster_buy"] = bool(len(buyers) >= 3 and row["buy_dollars"] > row["sell_dollars"])
    return row


def run(tickers: list[str], today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    universe = pd.read_parquet(config.VALUE_UNIVERSE_PARQUET)
    cik_by_ticker = dict(zip(universe["ticker"], universe["cik"]))
    session = make_edgar_session()
    rows = []
    for t in tickers:
        cik = cik_by_ticker.get(t)
        if not cik:
            continue
        rows.append(scan_ticker(t, int(cik), session, today=today))
    out = pd.DataFrame(rows, columns=INSIDER_COLUMNS)
    out.to_parquet(config.INSIDERS_PARQUET, index=False)
    log.info("insiders: %d names scanned, %d cluster buys", len(out), int(out["cluster_buy"].sum()))
    return out
