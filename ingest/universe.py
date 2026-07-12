"""Value-engine universe: S&P 500 + S&P MidCap 400, joined to SEC CIKs.

plan_value.md asks for "S&P 500 plus the next ~500 by market cap"; the
S&P MidCap 400 is the closest free, maintained stand-in for that next tier
(mid-caps are where screens find neglected value). Names without a CIK in
the SEC ticker map are dropped and logged — they cannot be valued from
EDGAR anyway.

Output: data/value_universe.parquet (ticker, name, sector, tier, cik, entity)
"""

from __future__ import annotations

import logging

import pandas as pd

from common import config
from common.http import get_with_retries, make_session
from ingest.edgar_facts import download_cik_map
from ingest.prices import WIKI_SP500_URL, parse_constituents_html

log = logging.getLogger("ete.universe")

WIKI_SP400_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_400_companies"


def fetch_value_universe(session=None, edgar_session=None) -> pd.DataFrame:
    session = session or make_session()
    frames = []
    for url, tier, min_rows in ((WIKI_SP500_URL, "sp500", 400), (WIKI_SP400_URL, "sp400", 300)):
        resp = get_with_retries(session, url)
        if resp is None:
            raise RuntimeError(f"could not fetch constituents from {url}")
        df = parse_constituents_html(resp.text, min_rows=min_rows)
        df["tier"] = tier
        frames.append(df)
    universe = (
        pd.concat(frames, ignore_index=True)
        .drop_duplicates("ticker")  # names promoted mid-year can appear in both
        .reset_index(drop=True)
    )

    cik_map = download_cik_map(edgar_session)
    merged = universe.merge(cik_map, on="ticker", how="left")
    missing = merged[merged["cik"].isna()]
    if len(missing):
        log.warning(
            "dropping %d names with no SEC CIK mapping: %s",
            len(missing), ", ".join(missing["ticker"].head(20)),
        )
    merged = merged.dropna(subset=["cik"]).reset_index(drop=True)
    merged["cik"] = merged["cik"].astype(int)
    return merged


def run() -> pd.DataFrame:
    config.ensure_dirs()
    universe = fetch_value_universe()
    universe.to_parquet(config.VALUE_UNIVERSE_PARQUET, index=False)
    log.info(
        "value universe: %d names (%d sp500, %d sp400) -> %s",
        len(universe), (universe["tier"] == "sp500").sum(),
        (universe["tier"] == "sp400").sum(), config.VALUE_UNIVERSE_PARQUET,
    )
    return universe


if __name__ == "__main__":
    config.setup_logging()
    run()
