"""Thesis journal: frozen pre-registered expectations per memo (plan §5/§8).

One append-only row per (ticker, memo_date): what the NEXT filings should
show if the thesis is right. Scored quarterly against actual filings — the
system's long-term memory and post-mortem dataset. Rows are never rewritten.
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.journal")

FIELDS = [
    "registered_at", "memo_date", "ticker", "verdict", "margin_of_safety",
    "value_conservative", "market_cap", "implied_growth",
    "exp_rev_growth_mid", "exp_gm_low", "exp_gm_high",
    "exp_buybacks_continue", "exp_nd_ebitda_max", "exp_fcf_ni_min",
    "thesis_driver",
]


def existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    prior = pd.read_csv(path, usecols=["ticker", "memo_date"], dtype=str)
    return set(zip(prior["ticker"], prior["memo_date"]))


def expectations_row(vrow: pd.Series, thesis: str, memo_date: date) -> dict:
    gm, sig = vrow.get("gross_margin", np.nan), vrow.get("gm_sigma_10y", np.nan)
    nd = vrow.get("nd_ebitda", np.nan)
    return {
        "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "memo_date": memo_date.isoformat(),
        "ticker": vrow["ticker"],
        "verdict": vrow["verdict"],
        "margin_of_safety": round(float(vrow["margin_of_safety"]), 4),
        "value_conservative": round(float(vrow["value_conservative"]), 0),
        "market_cap": round(float(vrow["market_cap"]), 0),
        "implied_growth": round(float(vrow["implied_growth"]), 4)
        if np.isfinite(vrow.get("implied_growth", np.nan)) else "",
        "exp_rev_growth_mid": round(float(vrow["rev_cagr_5y"]), 4)
        if np.isfinite(vrow.get("rev_cagr_5y", np.nan)) else "",
        "exp_gm_low": round(float(gm - 2 * sig), 4) if np.isfinite(gm) and np.isfinite(sig) else "",
        "exp_gm_high": round(float(gm + 2 * sig), 4) if np.isfinite(gm) and np.isfinite(sig) else "",
        "exp_buybacks_continue": bool(vrow.get("buyback_years_10y", 0) >= 8),
        "exp_nd_ebitda_max": round(float(max(nd + 0.5, 1.0)), 2) if np.isfinite(nd) else "",
        "exp_fcf_ni_min": 0.8,
        "thesis_driver": thesis[:200],
    }


GROWTH_FIELDS = [
    "registered_at", "memo_date", "ticker", "node", "theme", "sleeve",
    "idea_score", "crowding_z", "crowding_n_inputs", "gates_passed",
    "gate_notes", "n_evidence", "barbell_against", "max_position_dollars",
    "evidence_expectations", "exit_triggers",
]


def register(rows: list[dict], path: Path | None = None, fields: list[str] | None = None) -> int:
    path = path or config.JOURNAL_CSV
    fields = fields or FIELDS
    path.parent.mkdir(parents=True, exist_ok=True)
    seen = existing_keys(path)
    new = [r for r in rows if (str(r["ticker"]), str(r["memo_date"])) not in seen]
    if new:
        header = not path.exists()
        with path.open("a", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            if header:
                w.writeheader()
            w.writerows(new)
    log.info("journal: %d new expectation rows -> %s", len(new), path)
    return len(new)


def growth_expectations_row(idea: pd.Series, exit_triggers: list[str], memo_date: date) -> dict:
    return {
        "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "memo_date": memo_date.isoformat(),
        "ticker": idea["ticker"],
        "node": idea["node"],
        "theme": idea["theme"],
        "sleeve": idea["sleeve"],
        "idea_score": round(float(idea["idea_score"]), 4),
        "crowding_z": round(float(idea["crowding_z"]), 3),
        "crowding_n_inputs": int(idea["crowding_n_inputs"]),
        "gates_passed": bool(idea["gates_passed"]),
        "gate_notes": idea["gate_notes"],
        "n_evidence": int(idea["n_evidence"]),
        "barbell_against": idea.get("barbell_against", ""),
        "max_position_dollars": float(idea["max_position_dollars"]),
        "evidence_expectations": (
            "backlog/lead-time/pricing evidence strengthens at next two prints"
        ),
        "exit_triggers": " | ".join(exit_triggers),
    }
