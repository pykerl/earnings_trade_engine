import json
import zipfile
from datetime import date

import pandas as pd
import pytest

from common import config
from ingest import edgar_facts as ef


def _usd(entries):
    return {"units": {"USD": entries}}


def _fy(end, val, filed="2026-02-01", form="10-K", start=None):
    if start is None:
        y = int(end[:4]) - 1
        start = f"{y}{end[4:]}"
    return {"start": start, "end": end, "val": val, "form": form, "filed": filed, "fp": "FY"}


def _inst(end, val, form="10-K", filed="2026-02-01"):
    return {"end": end, "val": val, "form": form, "filed": filed}


def _company(revenue_tag="Revenues", years=range(2016, 2026)):
    ends = [f"{y}-12-31" for y in years]
    gaap = {
        revenue_tag: _usd([_fy(e, 100.0 + i) for i, e in enumerate(ends)]),
        "NetIncomeLoss": _usd([_fy(e, 10.0 + i) for i, e in enumerate(ends)]),
        "NetCashProvidedByUsedInOperatingActivities": _usd([_fy(e, 12.0 + i) for i, e in enumerate(ends)]),
        "PaymentsToAcquirePropertyPlantAndEquipment": _usd([_fy(e, 3.0) for e in ends]),
        "StockholdersEquity": _usd([_inst(e, 50.0 + i) for i, e in enumerate(ends)]),
        "Assets": _usd([_inst(e, 90.0 + i) for i, e in enumerate(ends)]),
        # quarterly revenue rows (~90d duration) + a YTD row that must be filtered
        "OperatingIncomeLoss": _usd(
            [_fy(e, 20.0) for e in ends]
            + [{"start": "2025-07-01", "end": "2025-09-30", "val": 5.5, "form": "10-Q",
                "filed": "2025-11-01", "fp": "Q3"},
               {"start": "2025-01-01", "end": "2025-09-30", "val": 15.0, "form": "10-Q",
                "filed": "2025-11-01", "fp": "Q3"}]  # YTD: 273d -> excluded
        ),
    }
    return {"cik": 123, "entityName": "Test Co", "facts": {"us-gaap": gaap}}


def test_parse_company_resolves_priority_tags_and_periods():
    adf, qdf, tags, missing = ef.parse_company(
        _company("RevenueFromContractWithCustomerExcludingAssessedTax"), "TST"
    )
    assert missing == []
    assert tags["revenue"] == "RevenueFromContractWithCustomerExcludingAssessedTax"
    assert len(adf) == 10  # ten fiscal years
    assert adf.iloc[-1]["revenue"] == 109.0
    assert adf.iloc[-1]["equity"] == 59.0
    # quarterly: the ~90d operating income row kept, the YTD row excluded
    assert len(qdf) == 1 and qdf.iloc[0]["operating_income"] == 5.5


def test_parse_company_falls_back_down_the_tag_list():
    _, _, tags, missing = ef.parse_company(_company("Revenues"), "TST")
    assert missing == [] and tags["revenue"] == "Revenues"


def test_amended_filing_wins_by_filed_date():
    payload = _company("Revenues")
    payload["facts"]["us-gaap"]["Revenues"]["units"]["USD"].append(
        _fy("2025-12-31", 999.0, filed="2026-06-01", form="10-K/A")
    )
    adf, _, _, _ = ef.parse_company(payload, "TST")
    assert adf.iloc[-1]["revenue"] == 999.0


def test_missing_core_concept_reports_it():
    payload = _company("Revenues")
    del payload["facts"]["us-gaap"]["NetCashProvidedByUsedInOperatingActivities"]
    adf, _, _, missing = ef.parse_company(payload, "TST")
    assert adf is None and missing == ["cfo"]


def test_instant_alignment_tolerates_offset_dates():
    payload = _company("Revenues")
    eq = payload["facts"]["us-gaap"]["StockholdersEquity"]["units"]["USD"]
    # equity measured two days before the flow period end
    eq[-1] = _inst("2025-12-29", 777.0)
    adf, _, _, _ = ef.parse_company(payload, "TST")
    assert adf.iloc[-1]["equity"] == 777.0


def _write_zip(tmp_path, companies):
    zp = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(zp, "w") as zf:
        for cik, payload in companies.items():
            zf.writestr(f"CIK{cik:010d}.json", json.dumps(payload))
    return zp


def test_build_fundamentals_drops_and_logs(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FUNDAMENTALS_DROPS_CSV", tmp_path / "drops.csv")
    monkeypatch.setattr(config, "UNMAPPED_TAGS_CSV", tmp_path / "unmapped.csv")
    monkeypatch.setattr(config, "EDGAR_DIR", tmp_path)
    bad = _company("Revenues")
    del bad["facts"]["us-gaap"]["Assets"]
    zp = _write_zip(tmp_path, {1: _company("Revenues"), 2: bad})
    universe = pd.DataFrame(
        {"ticker": ["GOOD", "BAD", "GONE"], "cik": [1, 2, 3], "entity": ["G", "B", "X"]}
    )
    # 2 of 3 dropped exceeds the 15% threshold -> must raise per plan
    with pytest.raises(RuntimeError, match="stop and show"):
        ef.build_fundamentals(universe, zip_path=zp)
    drops = pd.read_csv(tmp_path / "drops.csv")
    assert set(drops["ticker"]) == {"BAD", "GONE"}
    assert "unresolvable core" in drops.set_index("ticker").loc["BAD", "reason"]


def test_build_fundamentals_happy_path(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FUNDAMENTALS_DROPS_CSV", tmp_path / "drops.csv")
    monkeypatch.setattr(config, "UNMAPPED_TAGS_CSV", tmp_path / "unmapped.csv")
    monkeypatch.setattr(config, "EDGAR_DIR", tmp_path)
    zp = _write_zip(tmp_path, {i: _company("Revenues") for i in range(1, 8)})
    universe = pd.DataFrame(
        {"ticker": [f"T{i}" for i in range(1, 8)], "cik": list(range(1, 8)),
         "entity": ["x"] * 7}
    )
    annual, quarterly, drops = ef.build_fundamentals(universe, zip_path=zp)
    assert annual["ticker"].nunique() == 7
    assert len(drops) == 0
    assert (tmp_path / "tags_used.csv").exists()
