"""Validation gates for growth candidates (plan_reddit_growth §4).

Growth names won't pass Buffett gates; these test survivability, quality of
growth, dilution discipline, and — the important one — the two-source dated
evidence gate read from config/constraint_map.yaml.

Fundamentals come from the value engine's EDGAR layer: bulk-parsed where the
ticker is in the S&P 500/400 universe, single-company API fetch otherwise.
Foreign filers with no US companyfacts (thin-ADR reducer makers etc.) can't
be gated quantitatively: they get gate="no_edgar_data" + needs_human_review,
never a silent pass.

Output: data/growth_gates.parquet
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
import yaml

from common import config
from common.edgar import make_edgar_session
from features.disqualifiers import going_concern_hit
from features.quality import derive_series
from ingest.edgar_facts import fetch_company_via_api, parse_cik_map

log = logging.getLogger("ete.growth_gates")

CONSTRAINT_MAP = config.REPO_ROOT / "config" / "constraint_map.yaml"

RUNWAY_MIN_QUARTERS = 8
RULE_OF_40_MIN = 0.15       # "applied loosely" (plan §4): constraint owners are
                            # industrials, not SaaS — growth+FCF margin >= 15%
DILUTION_MAX_CAGR = 0.04    # growth names get more slack than value's 2%
SBC_REV_MAX = 0.15          # SBC as % of REVENUE for growth names


def load_constraint_map(path=CONSTRAINT_MAP) -> dict:
    return yaml.safe_load(path.read_text())["nodes"]


def candidate_table(nodes: dict) -> pd.DataFrame:
    """Flatten the constraint map into one row per candidate ticker."""
    rows = []
    for node_name, node in nodes.items():
        ev = [e for e in node.get("evidence", []) if e.get("source") and e.get("date")]
        for kind in ("pure_plays", "diversified"):
            for c in node.get(kind, []):
                rows.append(
                    {
                        "ticker": c["ticker"],
                        "name": c.get("name", c["ticker"]),
                        "node": node_name,
                        "theme": node["theme"],
                        "kind": kind[:-1] if kind.endswith("s") else kind,
                        "exposure": c.get("exposure", ""),
                        "listing": c.get("listing", "US"),
                        "confidence": node.get("confidence", "medium"),
                        "n_evidence": len(ev),
                        "needs_evidence": bool(c.get("needs_evidence", False)),
                        "crowded_names": ",".join(node.get("crowded_names", [])),
                        "capacity_watch": node.get("capacity_watch", ""),
                    }
                )
    return pd.DataFrame(rows).drop_duplicates(subset=["ticker", "node"]).reset_index(drop=True)


def get_fundamentals(ticker: str, universe_fund: pd.DataFrame, cik_map: dict, session) -> pd.DataFrame | None:
    have = universe_fund[
        (universe_fund["ticker"] == ticker) & (universe_fund["period_type"] == "FY")
    ]
    if len(have) >= 4:
        return have
    cik = cik_map.get(ticker)
    if not cik:
        return None
    res = fetch_company_via_api(ticker, int(cik), session)
    return res[0] if res else None


def quant_gates(annual: pd.DataFrame) -> dict:
    """Survivability / quality-of-growth / dilution from the FY series."""
    df = derive_series(annual)
    last = df.iloc[-1]
    fcf = df["fcf"]

    # runway: quarters of cash at trailing annual burn (only if burning)
    if last["fcf"] >= 0:
        runway_q, runway_pass = np.inf, True
    else:
        burn_q = -last["fcf"] / 4
        runway_q = float(last["cash"] / burn_q) if burn_q > 0 and np.isfinite(last["cash"]) else 0.0
        runway_pass = runway_q >= RUNWAY_MIN_QUARTERS

    rev_growth = df["revenue"].pct_change().iloc[-1]
    fcf_margin = last["fcf"] / last["revenue"] if last["revenue"] else np.nan
    rule40 = (rev_growth or 0) + (fcf_margin or 0)

    gm_recent = df["gross_margin"].tail(3).mean()
    gm_prior = df["gross_margin"].iloc[:-3].tail(3).mean()
    gm_trend_ok = not (np.isfinite(gm_recent) and np.isfinite(gm_prior) and gm_recent < gm_prior - 0.03)

    nd_ok = True
    if np.isfinite(last["nd_ebitda"]) and last["fcf"] >= 0:
        nd_ok = last["nd_ebitda"] <= 3.5

    shares = df["shares_diluted"].dropna()
    share_cagr = (
        (shares.iloc[-1] / shares.iloc[0]) ** (1 / max(len(shares) - 1, 1)) - 1
        if len(shares) >= 2 else np.nan
    )
    sbc_rev = last["sbc"] / last["revenue"] if np.isfinite(last.get("sbc", np.nan)) and last["revenue"] else np.nan
    dilution_ok = not (
        (np.isfinite(share_cagr) and share_cagr > DILUTION_MAX_CAGR)
        or (np.isfinite(sbc_rev) and sbc_rev > SBC_REV_MAX)
    )

    return {
        "runway_quarters": float(runway_q) if np.isfinite(runway_q) else 99.0,
        "gate_runway": bool(runway_pass),
        "rev_growth": float(rev_growth) if np.isfinite(rev_growth) else np.nan,
        "fcf_margin": float(fcf_margin) if np.isfinite(fcf_margin) else np.nan,
        "rule_of_40": float(rule40) if np.isfinite(rule40) else np.nan,
        "gate_rule40": bool(np.isfinite(rule40) and rule40 >= RULE_OF_40_MIN),
        "gate_gm_trend": bool(gm_trend_ok),
        "gate_leverage": bool(nd_ok),
        "share_cagr": float(share_cagr) if np.isfinite(share_cagr) else np.nan,
        "sbc_rev": float(sbc_rev) if np.isfinite(sbc_rev) else np.nan,
        "gate_dilution": bool(dilution_ok),
    }


def evidence_gate(row: pd.Series) -> bool:
    """>= 2 independent dated cited items on the node, and the specific
    candidate isn't flagged needs_evidence."""
    return int(row["n_evidence"]) >= 2 and not bool(row["needs_evidence"])


def run_gates(
    candidates: pd.DataFrame,
    universe_fund: pd.DataFrame,
    cik_map: dict,
    session=None,
    scan_going_concern: bool = True,
    today: date | None = None,
) -> pd.DataFrame:
    session = session or make_edgar_session()
    rows = []
    for _, c in candidates.iterrows():
        rec = c.to_dict()
        rec["gate_evidence"] = evidence_gate(c)
        annual = get_fundamentals(c["ticker"], universe_fund, cik_map, session)
        if annual is None or len(annual) < 4:
            rec.update(
                {
                    "edgar_data": False,
                    "gates_passed": False,
                    "gate_notes": "no_edgar_data (foreign filer or <4 FYs) — needs human review",
                    "needs_human_review": True,
                }
            )
            rows.append(rec)
            continue
        rec["edgar_data"] = True
        q = quant_gates(annual)
        rec.update(q)
        gc = False
        if scan_going_concern:
            cik = cik_map.get(c["ticker"])
            gc = going_concern_hit(int(cik), session, today=today) if cik else False
        rec["gate_going_concern"] = not gc
        gate_cols = [k for k in rec if k.startswith("gate_")]
        rec["gates_passed"] = all(bool(rec[k]) for k in gate_cols)
        rec["gate_notes"] = ";".join(k for k in gate_cols if not rec[k]) or "all pass"
        rec["needs_human_review"] = True  # exposure estimates always need eyes
        rows.append(rec)
    out = pd.DataFrame(rows)
    log.info(
        "growth gates: %d candidates, %d pass all, %d lack EDGAR data",
        len(out), int(out["gates_passed"].sum()), int((~out["edgar_data"]).sum()),
    )
    return out


def run(today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    nodes = load_constraint_map()
    candidates = candidate_table(nodes)
    universe_fund = (
        pd.read_parquet(config.FUNDAMENTALS_PARQUET)
        if config.FUNDAMENTALS_PARQUET.exists()
        else pd.DataFrame(columns=["ticker", "period_type"])
    )
    import json as _json

    cik_map_df = parse_cik_map(_json.loads(config.CIK_MAP_JSON.read_text()))
    cik_map = dict(zip(cik_map_df["ticker"], cik_map_df["cik"]))
    out = run_gates(candidates, universe_fund, cik_map, today=today)
    out.to_parquet(config.DATA_DIR / "growth_gates.parquet", index=False)
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
