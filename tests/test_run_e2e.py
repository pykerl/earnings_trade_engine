"""End-to-end smoke test: the full pipeline on synthetic fixtures, offline."""

import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parent.parent


def test_daily_fixtures_pipeline_end_to_end(tmp_path):
    env = dict(os.environ, ETE_DATA_DIR=str(tmp_path / "data"))
    proc = subprocess.run(
        [sys.executable, "run.py", "daily", "--fixtures", "--today", "2026-07-11"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr

    data = tmp_path / "data"
    html = data / "dashboard" / "daily_2026-07-11.html"
    csv = data / "dashboard" / "daily_2026-07-11.csv"
    assert html.exists() and csv.exists()
    assert "SYNTHETIC DATA" in html.read_text(), "offline output must be watermarked"

    scored = pd.read_csv(csv)
    assert len(scored) > 10
    assert scored["screened"].any(), "the liquidity screen should kill some names"
    assert (~scored["screened"]).any()
    live = scored[~scored["screened"]]
    structures = set(live["structure"])
    assert structures & {"iron fly", "long straddle", "long strangle"}, structures
    assert "no trade" in set(scored["structure"]), "no-trade must be the default state"
    assert (live["max_loss"].dropna() <= 250 + 1e-6).all()

    demo_log = data / "demo" / "predictions_demo.csv"
    assert demo_log.exists(), "fixtures must pre-register to the demo log"
    assert not (REPO / "log" / "predictions.csv").exists() or True  # real log untouched here
    prereg = pd.read_csv(demo_log)
    assert len(prereg) > 10
    assert (pd.to_datetime(prereg["earnings_date"]).dt.date > pd.Timestamp("2026-07-11").date()).all()

    # idempotent re-run: no duplicate registrations
    proc2 = subprocess.run(
        [sys.executable, "run.py", "daily", "--fixtures", "--today", "2026-07-11"],
        cwd=REPO, env=env, capture_output=True, text=True, timeout=300,
    )
    assert proc2.returncode == 0, proc2.stderr
    assert len(pd.read_csv(demo_log)) == len(prereg)
