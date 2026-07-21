import pandas as pd
import pytest

from picks import enrich


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(enrich, "VALUE_CACHE", tmp_path / "cache.parquet")
    monkeypatch.setattr(enrich, "ENRICHED_PARQUET", tmp_path / "enriched.parquet")
    monkeypatch.setattr(enrich.config, "VALUATIONS_PARQUET", tmp_path / "vals.parquet")
    monkeypatch.setattr(enrich.config, "DISQUALIFIERS_PARQUET", tmp_path / "dq.parquet")
    monkeypatch.setattr(enrich.config, "SCORED_PARQUET", tmp_path / "scored.parquet")
    monkeypatch.setattr(enrich.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr("picks.events.PICKS_PREDICTIONS_CSV", tmp_path / "j.csv")
    return tmp_path


def test_all_columns_degrade_to_na_when_siblings_absent(sandbox):
    out = (
        enrich.value_verdicts(["AAA"])
        .merge(enrich.crowding(["AAA"]), on="ticker")
        .merge(enrich.earnings_edge(["AAA"]), on="ticker")
    )
    row = out.iloc[0]
    assert row["value_verdict"].startswith("n/a")
    assert row["crowding"].startswith("n/a")
    assert row["earnings_edge"].startswith("n/a")


def test_value_verdict_cached_first_write_wins(sandbox):
    vals = pd.DataFrame([{"ticker": "AAA", "verdict": "pass", "moat_flag": True,
                          "margin_of_safety": -0.5}])
    vals.to_parquet(sandbox / "vals.parquet")
    first = enrich.value_verdicts(["AAA", "ZZZ"])
    assert first.set_index("ticker").loc["AAA", "value_verdict"] == "pass · moat · MoS -50%"
    assert "outside value universe" in first.set_index("ticker").loc["ZZZ", "value_verdict"]

    # restate the valuation file: cached verdict must NOT change
    pd.DataFrame([{"ticker": "AAA", "verdict": "ejected", "moat_flag": False,
                   "margin_of_safety": 2.0}]).to_parquet(sandbox / "vals.parquet")
    again = enrich.value_verdicts(["AAA"])
    assert again.iloc[0]["value_verdict"] == "pass · moat · MoS -50%"


def test_crowding_and_edge_refresh(sandbox):
    pd.DataFrame([{"ticker": "AAA", "mentions": 30, "velocity_z": 2.5, "upvotes": 1,
                   "rank": 1, "mentions_24h_ago": 5, "velocity_mode": "z"}]
                 ).to_parquet(sandbox / "mentions_latest.parquet")
    c = enrich.crowding(["AAA", "BBB"]).set_index("ticker")
    assert c.loc["AAA", "crowding"] == "z +2.5 · 30 mentions"
    assert c.loc["BBB", "crowding"].startswith("n/a")

    pd.DataFrame([{"ticker": "AAA", "implied_move_mid": 0.10, "fair_move": 0.072}]
                 ).to_parquet(sandbox / "scored.parquet")
    e = enrich.earnings_edge(["AAA", "BBB"]).set_index("ticker")
    assert "rich" in e.loc["AAA", "earnings_edge"]
    assert e.loc["AAA", "edge"] == pytest.approx(0.10 / 0.072 - 1)
    assert e.loc["BBB", "earnings_edge"].startswith("n/a")


def test_edge_falls_back_to_frozen_t1(sandbox):
    pd.DataFrame([{"ticker": "CCC", "implied_move_mid": 0.08, "fair_move": 0.09}]
                 ).to_csv(sandbox / "j.csv", index=False)
    e = enrich.earnings_edge(["CCC"]).set_index("ticker")
    assert "T-1 frozen" in e.loc["CCC", "earnings_edge"]
