"""13F-HR parser: what the configured value shops own (plan §1).

Holders come from config/gurus.yaml (seeded with Berkshire). For each
holder: latest 13F-HR accession from the submissions index -> accession
file index -> information-table XML -> issuer holdings.

Issuer names are matched to the universe by normalized entity name (13F
info tables carry CUSIPs, and free CUSIP->ticker mapping doesn't exist);
unmatched issuers are logged, never guessed. The overlay is 45 days stale
by construction — positions, not theses (plan §9).

Output: data/gurus.parquet (ticker, holder, value_kusd, shares)
"""

from __future__ import annotations

import logging
import re
from xml.etree import ElementTree

import pandas as pd
import yaml

from common import config
from common.edgar import edgar_get, make_edgar_session
from features.disqualifiers import _cached_submissions

log = logging.getLogger("ete.gurus")

INDEX_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/index.json"
FILE_URL = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{name}"

_SUFFIXES = re.compile(
    r"\b(INC|INCORPORATED|CORP|CORPORATION|CO|COMPANY|PLC|LTD|LP|HOLDINGS?|GROUP|"
    r"CL A|CL B|CLASS A|CLASS B|NEW|COM|DEL)\b\.?", re.I
)


def normalize_issuer(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9 ]", " ", str(name)).upper()
    s = _SUFFIXES.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_holders(path=None) -> list[dict]:
    path = path or config.GURUS_YAML
    payload = yaml.safe_load(path.read_text()) or {}
    return payload.get("holders", [])


def latest_13f_accession(submissions: dict) -> str | None:
    recent = (submissions.get("filings") or {}).get("recent") or {}
    for form, acc in zip(recent.get("form", []), recent.get("accessionNumber", [])):
        if str(form) == "13F-HR":
            return acc.replace("-", "")
    return None


def parse_infotable(xml_text: str) -> pd.DataFrame:
    """13F information table XML -> issuer/value/shares rows."""
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return pd.DataFrame(columns=["issuer", "value_kusd", "shares"])
    ns = ""
    if root.tag.startswith("{"):
        ns = root.tag.split("}")[0] + "}"
    rows = []
    for info in root.iter(f"{ns}infoTable"):
        issuer = info.findtext(f"{ns}nameOfIssuer") or ""
        value = float(info.findtext(f"{ns}value") or 0)
        shares = float(info.findtext(f"{ns}shrsOrPrnAmt/{ns}sshPrnamt") or 0)
        rows.append({"issuer": issuer, "value_kusd": value, "shares": shares})
    return pd.DataFrame(rows)


def fetch_holder_positions(holder: dict, session) -> pd.DataFrame:
    cik = int(holder["cik"])
    subs = _cached_submissions(cik, session)
    empty = pd.DataFrame(columns=["issuer", "value_kusd", "shares"])
    if not subs:
        return empty
    acc = latest_13f_accession(subs)
    if not acc:
        log.warning("no 13F-HR found for %s", holder["name"])
        return empty
    idx = edgar_get(session, INDEX_URL.format(cik=cik, acc_nodash=acc), retries=2)
    if idx is None:
        return empty
    try:
        files = [f["name"] for f in idx.json()["directory"]["item"]]
    except (ValueError, KeyError):
        return empty
    # the information table is the XML that isn't the primary_doc
    candidates = [f for f in files if f.lower().endswith(".xml") and "primary_doc" not in f.lower()]
    if not candidates:
        return empty
    resp = edgar_get(session, FILE_URL.format(cik=cik, acc_nodash=acc, name=candidates[0]), retries=2)
    if resp is None:
        return empty
    table = parse_infotable(resp.text)
    table["holder"] = holder["name"]
    return table


def match_to_universe(positions: pd.DataFrame, universe: pd.DataFrame) -> pd.DataFrame:
    uni = universe.copy()
    uni["norm"] = uni["entity"].fillna(uni["name"]).map(normalize_issuer)
    by_norm = uni.drop_duplicates("norm").set_index("norm")["ticker"]
    positions = positions.assign(norm=positions["issuer"].map(normalize_issuer))
    positions["ticker"] = positions["norm"].map(by_norm)
    unmatched = positions[positions["ticker"].isna()]
    if len(unmatched):
        log.info(
            "13F issuers not matched to universe (fine — most funds hold "
            "names outside it): %d of %d", len(unmatched), len(positions),
        )
    return positions.dropna(subset=["ticker"])[["ticker", "holder", "value_kusd", "shares"]]


def run() -> pd.DataFrame:
    config.ensure_dirs()
    universe = pd.read_parquet(config.VALUE_UNIVERSE_PARQUET)
    session = make_edgar_session()
    frames = [fetch_holder_positions(h, session) for h in load_holders()]
    positions = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if positions.empty:
        out = pd.DataFrame(columns=["ticker", "holder", "value_kusd", "shares"])
    else:
        out = match_to_universe(positions, universe)
    out.to_parquet(config.GURUS_PARQUET, index=False)
    log.info("gurus: %d universe positions across %d holders",
             len(out), out["holder"].nunique() if len(out) else 0)
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
