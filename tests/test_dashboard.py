from datetime import date

import numpy as np
import pandas as pd

from dashboard import daily


def _scored():
    base = {
        "name": "Rich Co", "sector": "Financials", "earnings_date": date(2026, 7, 16),
        "session": "BMO", "spot": 100.0, "expiry": "2026-07-17", "atm_strike": 100.0,
        "straddle_bid": 9.75, "straddle_mid": 10.0, "straddle_ask": 10.25,
        "implied_move_bid": 0.0975, "implied_move_mid": 0.10, "implied_move_ask": 0.1025,
        "spread_pct": 0.05, "open_interest": 1500, "volume": 100, "quote_ok": True,
        "fair_move": 0.06, "ci_low": 0.05, "ci_high": 0.07, "n_events": 10,
        "w_name": 0.6, "name_mean": 0.06, "pool": "g", "pool_mean": 0.05,
        "t_nu": 5.0, "t_scale": 0.03, "low_conf_share": 0.0,
        "source_agreement": "confirmed", "edge": 0.66, "z": 5.0,
        "screen_reason": "", "screened": False, "liq_mult": 1.0, "conf_mult": 0.8,
        "score": 4.0, "spread_cost_pct_of_edge": 12.5, "structure": "iron fly",
        "detail": "short 100 straddle @ bid, long 90P / 110C @ ask",
        "entry_side": "credit", "entry_price": 805.0, "max_gain": 805.0, "max_loss": 195.0,
        "flags": "",
    }
    rows = [dict(base, ticker="RICH")]
    rows.append(
        dict(
            base, ticker="CHEAP", structure="long straddle", entry_side="debit",
            entry_price=240.0, max_gain=np.inf, max_loss=240.0, edge=-0.4, score=-2.0,
        )
    )
    rows.append(
        dict(
            base, ticker="WIDE", screened=True, screen_reason="spread > 10%",
            structure="screened out", score=0.0, flags="spread > 10%",
            entry_price=np.nan, max_gain=np.nan, max_loss=np.nan, detail="",
        )
    )
    return pd.DataFrame(rows)


def _plan():
    import json

    return pd.DataFrame([
        {
            "ticker": "RICH", "name": "Rich Co", "structure": "iron fly",
            "contracts": 2, "entry_side": "credit", "entry_price": 805.0,
            "cash_flow": 1610.0, "position_risk": 390.0, "position_max_gain": 1610.0,
            "entry_by": date(2026, 7, 15), "earnings_date": date(2026, 7, 16),
            "session": "BMO", "expiry": "2026-07-17", "spot": 100.0,
            "legs_json": json.dumps([
                {"action": "SELL", "right": "CALL", "strike": 100.0},
                {"action": "SELL", "right": "PUT", "strike": 100.0},
                {"action": "BUY", "right": "CALL", "strike": 110.0},
                {"action": "BUY", "right": "PUT", "strike": 90.0},
            ]),
            "edge": 0.66, "score": 4.0, "implied_move_mid": 0.10,
            "fair_move": 0.06, "n_events": 10,
        }
    ])


def test_plan_section_renders_orders_dates_and_why():
    html_text = daily.render_html(_scored(), date(2026, 7, 12), plan=_plan())
    assert "Paper trade plan ($10,000 account)" in html_text
    assert "SELL 2 × RICH  $100 CALL  exp Fri Jul 17" in html_text
    assert "BUY 2 × RICH  $90 PUT  exp Fri Jul 17" in html_text
    assert "Place this order on <strong>Wed Jul 15</strong>" in html_text
    assert "Why this trade?" in html_text
    assert "overpriced" in html_text
    assert "$390" in html_text  # max loss for the position


def test_plan_section_empty_state():
    html_text = daily.render_html(_scored(), date(2026, 7, 12), plan=pd.DataFrame())
    assert "No positions today" in html_text


def test_dashboard_writes_html_and_csv(tmp_path):
    html_path, csv_path = daily.run(
        scored=_scored(), run_date=date(2026, 7, 12), out_dir=tmp_path, banner="TEST BANNER",
        plan=_plan(),
    )
    assert (tmp_path / "daily_2026-07-12_plan.csv").exists()
    html_text = html_path.read_text()
    assert "RICH" in html_text and "CHEAP" in html_text and "WIDE" in html_text
    assert "TEST BANNER" in html_text
    assert "unlimited" in html_text            # long straddle max gain
    assert "Screened out" in html_text
    for col_header in ["Implied (mid)", "Fair ± CI", "Edge", "Structure",
                       "Max gain / loss", "Spread / edge", "Conf", "Flags"]:
        assert col_header in html_text

    csv = pd.read_csv(csv_path)
    assert len(csv) == 3
    for col in ["ticker", "earnings_date", "session", "implied_move_mid", "implied_move_ask",
                "fair_move", "ci_low", "ci_high", "edge", "structure", "max_gain", "max_loss",
                "spread_cost_pct_of_edge", "conf_mult", "n_events", "flags"]:
        assert col in csv.columns


def test_screened_rows_stay_out_of_live_table(tmp_path):
    html_text = daily.render_html(_scored(), date(2026, 7, 12))
    live_section = html_text.split("Screened out")[0]
    assert "WIDE" not in live_section.split("Ranked")[1]
