import numpy as np
import pandas as pd
import pytest

from ingest import prices

SP500_HTML = """
<table>
  <tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th>
      <th>Headquarters Location</th><th>Date added</th><th>CIK</th><th>Founded</th></tr>
""" + "\n".join(
    f"<tr><td>T{i}</td><td>Company {i}</td><td>Sector{i % 3}</td><td>Sub{i}</td>"
    f"<td>City</td><td>2000-01-01</td><td>{i}</td><td>1900</td></tr>"
    for i in range(450)
) + """
  <tr><td>BRK.B</td><td>Berkshire</td><td>Financials</td><td>Multi</td>
      <td>Omaha</td><td>2010-02-16</td><td>1067983</td><td>1839</td></tr>
</table>
"""


def test_parse_sp500_html_normalizes_tickers():
    uni = prices.parse_sp500_html(SP500_HTML)
    assert "BRK-B" in set(uni["ticker"])
    assert {"ticker", "name", "sector", "sub_industry"} <= set(uni.columns)
    assert len(uni) == 451


def test_parse_sp500_html_rejects_truncated_table():
    html = """<table><tr><th>Symbol</th><th>Security</th><th>GICS Sector</th>
    <th>GICS Sub-Industry</th></tr><tr><td>A</td><td>A Co</td><td>S</td><td>SS</td></tr></table>"""
    with pytest.raises(RuntimeError):
        prices.parse_sp500_html(html)


def _fake_wide(tickers, days=5):
    idx = pd.bdate_range("2026-01-05", periods=days, tz="America/New_York")
    cols = pd.MultiIndex.from_product([tickers, ["Open", "High", "Low", "Close", "Adj Close", "Volume"]])
    raw = pd.DataFrame(np.nan, index=idx, columns=cols)
    for t in tickers:
        base = 100.0 + hash(t) % 50
        raw.loc[:, (t, "Open")] = base
        raw.loc[:, (t, "High")] = base * 1.01
        raw.loc[:, (t, "Low")] = base * 0.99
        raw.loc[:, (t, "Close")] = base * 1.005
        raw.loc[:, (t, "Adj Close")] = base * 1.005
        raw.loc[:, (t, "Volume")] = 1_000_000
    return raw


def test_wide_to_long_shapes_and_skips_missing():
    raw = _fake_wide(["AAA", "BBB"])
    raw.loc[:, ("BBB", "Close")] = np.nan  # simulate a dead ticker
    long = prices.wide_to_long(raw, ["AAA", "BBB", "CCC"])  # CCC absent entirely
    assert set(long["ticker"]) == {"AAA"}
    assert list(long.columns) == ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
    assert long["date"].dt.tz is None
    assert len(long) == 5
