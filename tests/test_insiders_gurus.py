import pandas as pd

from ingest import gurus, insiders

FORM4_BUY = """<?xml version="1.0"?>
<ownershipDocument>
  <reportingOwner><reportingOwnerId><rptOwnerName>DOE JANE</rptOwnerName></reportingOwnerId></reportingOwner>
  <nonDerivativeTable>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>P</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>1000</value></transactionShares>
        <transactionPricePerShare><value>50.5</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
    <nonDerivativeTransaction>
      <transactionCoding><transactionCode>A</transactionCode></transactionCoding>
      <transactionAmounts>
        <transactionShares><value>500</value></transactionShares>
        <transactionPricePerShare><value>0</value></transactionPricePerShare>
      </transactionAmounts>
    </nonDerivativeTransaction>
  </nonDerivativeTable>
</ownershipDocument>"""


def test_parse_form4_keeps_open_market_only():
    rows = insiders.parse_form4(FORM4_BUY)
    assert len(rows) == 1  # the award (code A) is excluded
    assert rows[0] == {"owner": "DOE JANE", "code": "P", "dollars": 50500.0}


def test_form4_doc_listing_filters_form_and_date():
    subs = {
        "filings": {
            "recent": {
                "form": ["4", "4", "10-K", "4"],
                "filingDate": ["2026-06-01", "2025-01-01", "2026-02-01", "2026-03-05"],
                "accessionNumber": ["0001-26-000001", "0001-25-000009", "x", "0001-26-000002"],
                "primaryDocument": ["xslF345X05/a.xml", "b.xml", "k.htm", "c.xml"],
            }
        }
    }
    docs = insiders._form4_docs(subs, since="2025-07-13")
    assert docs == [("000126000001", "a.xml"), ("000126000002", "c.xml")]


INFOTABLE = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable>
    <nameOfIssuer>APPLE INC</nameOfIssuer>
    <value>75000000</value>
    <shrsOrPrnAmt><sshPrnamt>300000000</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt>
  </infoTable>
  <infoTable>
    <nameOfIssuer>MYSTERY HOLDCO LLC</nameOfIssuer>
    <value>1000</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt></shrsOrPrnAmt>
  </infoTable>
</informationTable>"""


def test_parse_infotable_with_namespace():
    df = gurus.parse_infotable(INFOTABLE)
    assert len(df) == 2
    assert df.iloc[0]["issuer"] == "APPLE INC"
    assert df.iloc[0]["shares"] == 300000000


def test_issuer_normalization_and_matching():
    assert gurus.normalize_issuer("Apple Inc.") == gurus.normalize_issuer("APPLE INC")
    assert gurus.normalize_issuer("Coca-Cola Co") == gurus.normalize_issuer("COCA COLA COMPANY")
    positions = gurus.parse_infotable(INFOTABLE).assign(holder="Berkshire Hathaway")
    universe = pd.DataFrame(
        {"ticker": ["AAPL"], "name": ["Apple"], "entity": ["Apple Inc."]}
    )
    matched = gurus.match_to_universe(positions, universe)
    assert list(matched["ticker"]) == ["AAPL"]  # mystery holdco dropped, not guessed


def test_load_holders_seeded_with_berkshire():
    holders = gurus.load_holders()
    assert any("Berkshire" in h["name"] for h in holders)
    assert all(str(h["cik"]).isdigit() for h in holders)
