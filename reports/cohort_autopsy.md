# WSB cohort autopsy — Stage A (2026-07-12)

Was the crowd's return skill, beta, or momentum? Equal-weight buy-and-hold
from publication date, adjusted closes (yfinance), Fama-French daily factors.
**This calibrates the funnel; it is not a buy list.**

## wsb_2026_index — WallStreetBets 2026 Index — ten stocks chosen by the sub

- Published: 2026-01-02 · names: ASTS, RKLB, GOOGL, AMZN, NBIS, RDDT, MU, IREN, TSLA, PLTR
- **Total return since publication: 31.7%** · SPY: 11.1% · QQQ: 18.6%
- Max drawdown: -27.3% · hit rate: 50% of names positive
- Contribution concentration: top 2 (MU, NBIS) supplied 35.5pts of the 31.7% EW return (112% of it)

### Per-name returns since publication

| Ticker | Return |
|---|---|
| MU | 210.7% |
| NBIS | 144.2% |
| GOOGL | 13.5% |
| AMZN | 8.3% |
| RKLB | 6.6% |
| IREN | -3.7% |
| TSLA | -6.9% |
| ASTS | -12.2% |
| RDDT | -19.2% |
| PLTR | -24.5% |

### Entry-lag sensitivity (buy N days after publication)

| Lag | Cohort | SPY | QQQ |
|---|---|---|---|
| 0d | 31.7% | 11.1% | 18.6% |
| 7d | 21.9% | 9.3% | 16.0% |
| 30d | 22.8% | 9.1% | 16.1% |
| 90d | 36.6% | 15.4% | 24.2% |

### Factor decomposition (daily, Mkt-RF + Momentum)

- Window: 101 trading days, factor data through 2026-05-29
- Market beta: **1.91** · momentum beta: **0.85** · R²: 0.57
- **Residual alpha: 39.1%/yr** — the only number that can be called picking skill

## wsb_2026_upvotes — 2026 upvote-tally variant (adds POET, SOFI, PATH per plan §1)

- Published: 2026-01-02 · names: ASTS, RKLB, GOOGL, AMZN, NBIS, RDDT, MU, IREN, TSLA, PLTR, POET, SOFI, PATH
- **Total return since publication: 21.1%** · SPY: 11.1% · QQQ: 18.6%
- Max drawdown: -28.9% · hit rate: 46% of names positive
- Contribution concentration: top 2 (MU, NBIS) supplied 27.3pts of the 21.1% EW return (129% of it)

### Per-name returns since publication

| Ticker | Return |
|---|---|
| MU | 210.7% |
| NBIS | 144.2% |
| POET | 16.1% |
| GOOGL | 13.5% |
| AMZN | 8.3% |
| RKLB | 6.6% |
| IREN | -3.7% |
| TSLA | -6.9% |
| ASTS | -12.2% |
| RDDT | -19.2% |
| PLTR | -24.5% |
| PATH | -26.4% |
| SOFI | -31.6% |

### Entry-lag sensitivity (buy N days after publication)

| Lag | Cohort | SPY | QQQ |
|---|---|---|---|
| 0d | 21.1% | 11.1% | 18.6% |
| 7d | 13.2% | 9.3% | 16.0% |
| 30d | 19.1% | 9.1% | 16.1% |
| 90d | 32.7% | 15.4% | 24.2% |

### Factor decomposition (daily, Mkt-RF + Momentum)

- Window: 101 trading days, factor data through 2026-05-29
- Market beta: **2.04** · momentum beta: **0.77** · R²: 0.56
- **Residual alpha: 16.0%/yr** — the only number that can be called picking skill

## wsb_2025 — WSB 2025 crowd portfolio (top-voted basket; press-reported ~76% for 2025)

> ⚠️ **PARTIAL COHORT — constituents unverified.** Press confirms the survey existed, the upvote-tally methodology, and a ~76% cumulative 2025 return, and names TSLA, PLTR, HOOD, NVDA as retail 'long-term winners' with ASTS prominent (+260% in 2025). No accessible free source enumerates the full list; reddit.com is blocked from this sandbox. The autopsy runs this PARTIAL press-attested cohort, clearly labeled; replace with the full thread list when available.

- Published: 2025-01-02 · names: TSLA, PLTR, HOOD, NVDA, ASTS
- **Total return since publication: 110.3%** · SPY: 31.3% · QQQ: 43.3%
- Max drawdown: -38.5% · hit rate: 100% of names positive
- Contribution concentration: top 2 (ASTS, HOOD) supplied 84.5pts of the 110.3% EW return (77% of it)

### Per-name returns since publication

| Ticker | Return |
|---|---|
| ASTS | 238.8% |
| HOOD | 183.9% |
| PLTR | 68.6% |
| NVDA | 52.8% |
| TSLA | 7.5% |

### Entry-lag sensitivity (buy N days after publication)

| Lag | Cohort | SPY | QQQ |
|---|---|---|---|
| 0d | 110.3% | 31.3% | 43.3% |
| 7d | 110.9% | 32.3% | 44.1% |
| 30d | 99.2% | 28.5% | 41.1% |
| 90d | 114.0% | 35.6% | 53.3% |

### Factor decomposition (daily, Mkt-RF + Momentum)

- Window: 351 trading days, factor data through 2026-05-29
- Market beta: **2.26** · momentum beta: **0.67** · R²: 0.57
- **Residual alpha: 31.6%/yr** — the only number that can be called picking skill

## Reading guide

- A high market/momentum beta with near-zero residual alpha means the cohort's
  return was the tape, not the picks — use Reddit as a THEME scout only.
- Entry-lag decay measures how much is gone by the time the list is public;
  it directly calibrates how to treat live mention spikes.
- The 2025 row is a partial, press-attested cohort until the original thread
  list is supplied — treat its numbers as indicative, not evidential.