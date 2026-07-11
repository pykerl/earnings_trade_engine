import json
from types import SimpleNamespace

import pytest

from dashboard import charts

FLY = SimpleNamespace(
    ticker="RICH", spot=100.0, contracts=2, cash_flow=1610.0,  # 2 x $805 credit
    implied_move_mid=0.10, fair_move=0.06,
    legs_json=json.dumps([
        {"action": "SELL", "right": "CALL", "strike": 100.0},
        {"action": "SELL", "right": "PUT", "strike": 100.0},
        {"action": "BUY", "right": "CALL", "strike": 110.0},
        {"action": "BUY", "right": "PUT", "strike": 90.0},
    ]),
)

STRADDLE = SimpleNamespace(
    ticker="VOL", spot=50.0, contracts=1, cash_flow=-240.0,  # $240 debit
    implied_move_mid=0.04, fair_move=0.07,
    legs_json=json.dumps([
        {"action": "BUY", "right": "CALL", "strike": 50.0},
        {"action": "BUY", "right": "PUT", "strike": 50.0},
    ]),
)


def test_iron_fly_payoff_shape():
    # pinned at the short strike: keep the full credit
    assert charts.payoff_at(0.0, FLY) == pytest.approx(1610.0)
    # beyond the wings: max loss = width(10) x 200 shares - credit
    assert charts.payoff_at(0.15, FLY) == pytest.approx(1610.0 - 10 * 200)
    assert charts.payoff_at(-0.15, FLY) == pytest.approx(1610.0 - 10 * 200)


def test_straddle_payoff_shape():
    assert charts.payoff_at(0.0, STRADDLE) == pytest.approx(-240.0)
    # +10% move: call worth $5 x 100 = $500 -> +$260
    assert charts.payoff_at(0.10, STRADDLE) == pytest.approx(260.0)


def test_breakevens_match_credit():
    half = charts.chart_domain(FLY, [0.02, -0.05])
    bes = charts.breakeven_moves(charts.payoff_knots(FLY, half))
    # per-share credit 1610/200 = 8.05 -> breakevens at 100 +/- 8.05
    assert sorted(round(b, 4) for b in bes) == [-0.0805, 0.0805]


def test_bins_classify_wins_exactly():
    half = charts.chart_domain(FLY, [0.0, 0.05, -0.12])
    bins = charts.bin_moves([0.0, 0.05, -0.12], FLY, half)
    wins = sum(b["win"] for b in bins)
    losses = sum(b["loss"] for b in bins)
    assert (wins, losses) == (2, 1)  # 0% and +5% inside breakevens, -12% outside
    w, t = charts.win_stats([0.0, 0.05, -0.12], FLY)
    assert (w, t) == (2, 3)


def test_domain_covers_strikes_and_history():
    half = charts.chart_domain(FLY, [0.31])
    assert half >= 0.31, "domain must cover the largest historical move"
    assert half <= 0.60


def test_build_chart_html_contract():
    moves = [0.01, -0.02, 0.05, -0.09, 0.12, 0.0, -0.04, 0.03]
    html_out = charts.build_chart(FLY, moves, "ch-RICH")
    assert "<svg" in html_out and "chart-data" in html_out
    assert "Table view" in html_out, "table-view twin is mandatory"
    assert "past move → win" in html_out and "past move → loss" in html_out
    assert 'tabindex="0"' in html_out, "keyboard focus required"
    payload = json.loads(html_out.split('class="chart-data">')[1].split("</script>")[0])
    assert payload["total"] == len(moves)
    assert sum(b[2] + b[3] for b in payload["bins"]) == len(moves)
