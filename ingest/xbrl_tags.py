"""XBRL concept -> ordered candidate-tag mapping (the ugly part, plan §7).

Filers use different us-gaap tags for the same economic concept (Revenues vs
RevenueFromContractWithCustomerExcludingAssessedTax vs SalesRevenueNet...).
Each concept below carries an ordered priority list: the FIRST candidate tag
with usable data wins, and the winner is recorded per company so mappings
are auditable. A company missing any REQUIRED_CORE concept is DROPPED and
logged — never imputed (plan: prefer dropping over guessing).

kind:  "flow"    — duration concept, annual value spans the fiscal year
       "instant" — balance-sheet concept, measured at period end
unit:  "USD" or "shares"
"""

from __future__ import annotations

CONCEPTS: dict[str, dict] = {
    # ---- income statement (flows, USD) --------------------------------------
    "revenue": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            "Revenues",
            "SalesRevenueNet",
            "RevenueFromContractWithCustomerIncludingAssessedTax",
            "SalesRevenueGoodsNet",
            "SalesRevenueServicesNet",
            "RegulatedAndUnregulatedOperatingRevenue",
        ],
    },
    "cost_of_revenue": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "CostOfRevenue",
            "CostOfGoodsAndServicesSold",
            "CostOfGoodsSold",
            "CostOfServices",
        ],
    },
    "gross_profit": {"kind": "flow", "unit": "USD", "tags": ["GrossProfit"]},
    "operating_income": {"kind": "flow", "unit": "USD", "tags": ["OperatingIncomeLoss"]},
    "pretax_income": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            "IncomeLossFromContinuingOperationsBeforeIncomeTaxesForeignAndDomestic(Deprecated)",
        ],
    },
    "tax_expense": {"kind": "flow", "unit": "USD", "tags": ["IncomeTaxExpenseBenefit"]},
    "net_income": {
        "kind": "flow", "unit": "USD",
        "tags": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    },
    "interest_expense": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "InterestExpense",
            "InterestExpenseDebt",
            "InterestExpenseNonoperating",
            "InterestAndDebtExpense",
        ],
    },
    # ---- cash flow statement (flows, USD) -----------------------------------
    "cfo": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "NetCashProvidedByUsedInOperatingActivities",
            "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        ],
    },
    "capex": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "PaymentsToAcquirePropertyPlantAndEquipment",
            "PaymentsToAcquireProductiveAssets",
            "PaymentsForCapitalImprovements",
            "PaymentsToAcquireOtherPropertyPlantAndEquipment",
        ],
    },
    "dna": {
        "kind": "flow", "unit": "USD",
        "tags": [
            "DepreciationDepletionAndAmortization",
            "DepreciationAmortizationAndAccretionNet",
            "DepreciationAndAmortization",
            "Depreciation",
        ],
    },
    "sbc": {
        "kind": "flow", "unit": "USD",
        "tags": ["ShareBasedCompensation", "AllocatedShareBasedCompensationExpense"],
    },
    "dividends_paid": {
        "kind": "flow", "unit": "USD",
        "tags": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
    },
    "buybacks": {
        "kind": "flow", "unit": "USD",
        "tags": ["PaymentsForRepurchaseOfCommonStock"],
    },
    "shares_diluted": {
        "kind": "flow", "unit": "shares",
        "tags": [
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            "WeightedAverageNumberOfSharesOutstandingBasic",
        ],
    },
    # ---- balance sheet (instants, USD unless noted) --------------------------
    "cash": {
        "kind": "instant", "unit": "USD",
        "tags": [
            "CashAndCashEquivalentsAtCarryingValue",
            "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        ],
    },
    "st_investments": {
        "kind": "instant", "unit": "USD",
        "tags": ["ShortTermInvestments", "MarketableSecuritiesCurrent"],
    },
    "lt_debt": {
        "kind": "instant", "unit": "USD",
        "tags": [
            "LongTermDebtNoncurrent",
            "LongTermDebt",
            "LongTermDebtAndCapitalLeaseObligations",
        ],
    },
    "st_debt": {
        "kind": "instant", "unit": "USD",
        "tags": [
            "LongTermDebtCurrent",
            "DebtCurrent",
            "ShortTermBorrowings",
            "LongTermDebtAndCapitalLeaseObligationsCurrent",
        ],
    },
    "equity": {
        "kind": "instant", "unit": "USD",
        "tags": [
            "StockholdersEquity",
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        ],
    },
    "assets": {"kind": "instant", "unit": "USD", "tags": ["Assets"]},
    "liabilities": {"kind": "instant", "unit": "USD", "tags": ["Liabilities"]},
    "current_assets": {"kind": "instant", "unit": "USD", "tags": ["AssetsCurrent"]},
    "current_liabilities": {"kind": "instant", "unit": "USD", "tags": ["LiabilitiesCurrent"]},
    "retained_earnings": {
        "kind": "instant", "unit": "USD", "tags": ["RetainedEarningsAccumulatedDeficit"],
    },
    # dei namespace (instant, shares)
    "shares_outstanding": {
        "kind": "instant", "unit": "shares", "namespace": "dei",
        "tags": ["EntityCommonStockSharesOutstanding"],
    },
}

# a company that cannot resolve every one of these is dropped, not imputed
REQUIRED_CORE = ("revenue", "net_income", "cfo", "capex", "equity", "assets")

# concepts where a missing series is fine (recorded as NaN downstream)
OPTIONAL = tuple(c for c in CONCEPTS if c not in REQUIRED_CORE)
