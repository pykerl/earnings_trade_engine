# plan_value.md — Buffett/Munger-Style Deep Value Engine (Free Data)

Goal: a systematic pipeline that screens the market like a value investor — **wonderful companies at fair prices, held indefinitely** — surfaces the undervalued names going into Q2 2026 earnings season, mines public filings for evidence, and outputs a one-page **thesis memo per candidate where the "why" is the product**, not just a rank.

Same build philosophy as `plan_free_weekend.md`: free data only, weekend-buildable core, honest about what a quant screen can and cannot judge. Key difference from the options engine: this is a **low-frequency, buy-and-hold process**. Earnings season is an information catalyst and occasional mispricing window — not a trading trigger.

---

## 0. Investment philosophy encoded as rules

The pipeline operationalizes the Buffett/Munger checklist in four gates, applied in order:

1. **Understandable business** (circle of competence): stable, cash-generative business models; flag serial acquirers, opaque financials, and businesses whose economics changed recently.
2. **Durable moat**: judged by *quantitative footprints* a moat leaves — persistently high ROIC without high leverage, stable/rising gross margins, low earnings variability, pricing power evidence.
3. **Able, honest management**: capital allocation record — buybacks executed at low valuations, sensible dividends, no serial dilution, insider ownership and buying, conservative accounting (accruals low vs cash flow).
4. **Fair price with margin of safety**: multiple independent valuation lenses; require price meaningfully below conservative intrinsic value.

**Munger inversion is built in:** every candidate must pass a *disqualifier* checklist (what kills this?) before it can rank, and every memo includes a pre-mortem ("it's 2031 and this lost money — why?").

Guardrail the whole plan respects: **statistically cheap ≠ value.** Low P/E junk is the classic value trap. Quality gates run *before* cheapness ever enters the score.

---

## 1. Free data source map

| Need | Source | Notes |
|---|---|---|
| 10+ yrs of fundamentals for every US filer | **SEC EDGAR `companyfacts` bulk file** (companyfacts.zip, refreshed nightly) + per-company XBRL API | The centerpiece. Free, official, complete: revenue, NI, CFO, capex, D&A, debt, equity, shares out, segment data — every 10-K/10-Q as-filed |
| Filing text (10-K risk factors, MD&A, proxy) | EDGAR full-text search API + direct filing pulls | For the memo generator's evidence quotes and red-flag scans |
| Insider transactions | EDGAR Form 4 feeds | Cluster-buying signal; free |
| What great value investors own | EDGAR 13F-HR parsing (Berkshire, plus a configurable list of respected value shops) | Free; 45-day lag is fine at buy-and-hold horizon |
| Prices, dividends, splits, market cap | yfinance | Same workhorse as the options plan |
| Earnings calendar (season overlay) | yfinance + Finnhub cross-check | Reuse `ingest/calendar.py` from the options build |
| Risk-free / discount-rate anchor | FRED 10-yr Treasury | Buffett's stated yardstick for opportunity cost |
| Sector/industry classification | EDGAR SIC codes + yfinance sector | For peer pools |

No paid screeners needed — EDGAR companyfacts replaces them entirely, and using as-filed XBRL means the numbers are the company's own sworn filings, not a vendor's adjustments.

---

## 2. Metric layer (`features/`)

All computed from EDGAR XBRL, 10-year history where available:

**Quality / moat footprints**
- ROIC = NOPAT / (net debt + equity), 10-yr median and trend; moat flag if median > 12–15% *without* net-debt/EBITDA > 2.5
- Gross & operating margin: level, stability (10-yr σ), trend
- FCF conversion: FCF/NI 10-yr average (want ≥ 0.8; accruals red flag if persistently < 0.6)
- Revenue durability: 10-yr growth consistency, drawdown in 2020 as a stress observation
- Reinvestment economics: incremental ROIC (ΔNOPAT / Δinvested capital over 5 yrs)

**Balance sheet / survivability**
- Net debt/EBITDA, interest coverage, debt maturity notes (from filings), Altman-Z as a coarse trap filter

**Management / capital allocation**
- Share count trajectory (10-yr CAGR — want shrinking or flat)
- Buyback timing quality: dollars repurchased in low-valuation years vs high
- Dividend record; SBC as % of FCF; insider net buying (Form 4, trailing 12m)

**Owner earnings (the Buffett number)**
- Owner earnings ≈ NI + D&A + other non-cash − **maintenance capex** (proxied as min(depreciation, capex) with a growth-capex adjustment where segment data allows; state the proxy explicitly in every memo)

---

## 3. Valuation layer (`valuation/`) — four independent lenses

No single model gets to decide. Each name gets:

1. **Owner-earnings yield** vs 10-yr Treasury: yield = owner earnings / EV; require a spread (e.g., ≥ 4–5% over the 10-yr) — the "equity bond" framing.
2. **Conservative two-stage DCF**: growth capped at trailing 10-yr revenue CAGR (and hard-capped at ~10%), fade to 2.5% terminal, discount at 10% flat (a hurdle rate, not CAPM theater). Report a *range* across growth ±2pts.
3. **Earnings power value (Greenwald EPV)**: zero-growth valuation of normalized current earnings — what you get if the moat only *defends*. If price < EPV, growth is free.
4. **Reverse DCF**: solve for the growth rate the current price implies; memo states it plainly ("the market is paying for 9%/yr for a decade — history says this business does 5%").

**Margin of safety score** = discount of price to the *most conservative* of lenses 1–3, not the average. Require ≥ 25–30% for the buy list, ≥ 15% for the watch list.

---

## 4. Disqualifier checklist (Munger inversion, runs before ranking)

Auto-flag and demote/eject on:
- Revenue in structural decline (3+ yr negative trend) without offsetting FCF durability
- Net debt/EBITDA > 3 or interest coverage < 4
- Serial dilution (share count +>2%/yr) or SBC > 20% of FCF
- Accruals divergence (NI growing, CFO not)
- Auditor changes, going-concern language, late filings, restatements (EDGAR full-text scan)
- Heavy customer concentration (10-K risk-factor scan)
- Industry facing visible substitution risk — **cannot be fully automated; flagged for the human-review step, never silently passed**

---

## 5. The "why" — thesis memo generator (`memos/`) — the core deliverable

One page per candidate, auto-drafted from the data + filing excerpts, structured for a human (you) to edit and sign off. Template:

1. **Business in two sentences** (from 10-K Item 1, compressed)
2. **Moat evidence** — the numbers, not adjectives: "ROIC 10-yr median 21% with net cash; gross margin 58–61% band for a decade; raised prices through 2022 inflation with volumes intact (MD&A cite)"
3. **Management & capital allocation** — buyback record with valuation context, insider activity, SBC discipline
4. **Owner earnings & the four valuations** — table, with the maintenance-capex assumption stated
5. **What the market is missing (the thesis)** — templated from *which* signal drives the discount: sentiment/sector selloff, temporary margin compression with mean-reversion evidence, misunderstood segment, post-earnings overreaction
6. **Bear case & pre-mortem** — steelmanned; the disqualifier flags that *almost* fired
7. **Earnings-season note** — reports [date]; what one quarter can and cannot tell us about this thesis; pre-registered expectation so the print updates beliefs instead of anchoring them
8. **Verdict**: Buy-and-hold candidate / Watch (needs price) / Pass — with the single sentence Munger would demand: *why this, at this price, instead of an index fund.*

Memos are generated as Markdown, versioned in git — the thesis journal becomes the system's long-term memory and post-mortem dataset.

---

## 6. Earnings-season overlay (the "going into Q2 season" ask)

- Join the ranked value list against the earnings calendar → **"Undervalued & Reporting Soon"** dashboard tab: name, report date, margin of safety, thesis one-liner, what to watch in the print.
- Two explicit modes, kept separate on the dashboard:
  - **Conviction entries**: already-passed candidates where you'd buy regardless of the print; earnings is just the next data point.
  - **Overreaction watch**: quality names on the watch list where a fearful post-earnings drop could create the margin of safety. Pre-set "interested below $X" levels *before* the print (decided calmly, executed mechanically — the whole point of the pre-registration habit).
- Anti-pattern guard, stated on the dashboard itself: this process never buys *because* earnings are coming. A quarter is noise against a 10-year owner-earnings record.

---

## 7. Weekend build schedule

**Saturday — fundamentals engine**
- Block 1: download EDGAR companyfacts bulk zip; parse into a tidy fundamentals table for S&P 500 + optionally the next ~500 by market cap (mid-caps are where screens find neglected value); map XBRL tags (the ugly part — Revenue/Revenues/RevenueFromContract... — budget real time for tag reconciliation).
- Block 2: compute the §2 metric layer + §4 disqualifier flags; sanity-check five names you know well against their actual 10-Ks.

**Sunday — valuation, memos, dashboard**
- Block 3: four valuation lenses + margin-of-safety score; rank.
- Block 4: memo generator (data-driven sections fully automated; filing-text sections pull the relevant 10-K/MD&A excerpts for you to compress in review); earnings-season overlay joining the calendar; output ranked HTML dashboard + a `memos/` folder for the top 15.

**Post-weekend cadence:** ~30 min/week — refresh prices (valuations drift, fundamentals don't), regenerate the reporting-soon tab, review any new 10-Q of a held/watched name, append to the thesis journal.

---

## 8. Measuring "how well it does"

Buy-and-hold verdicts take years, so track leading indicators honestly:
- **Thesis accuracy journal**: each memo's pre-registered expectations vs subsequent filings (did margins mean-revert? did buybacks continue?) — scored quarterly.
- **Watch-list discipline**: how often did pre-set entry prices get hit, and what happened after (vs impulse entries)?
- **Cohort tracking**: total return of each quarter's buy-list cohort vs SPY, reported with the caveat that <3 yrs of cohorts is anecdote.
- **Trap autopsy**: any name that fell >30% post-selection gets a written post-mortem — which disqualifier *should* have fired?

---

## 9. Honest limitations

- A screen measures the *footprints* of a moat, not the moat. The human-review step on business quality is load-bearing, not decorative.
- Maintenance-capex is an estimate; owner earnings inherit its error. Every memo states it.
- XBRL tag inconsistency across filers is the biggest engineering risk — expect ~10% of names to need manual tag mapping; drop rather than guess.
- 13F guru overlay is 45 days stale and shows positions, not theses.
- Value spreads can stay wide for years; this process will look wrong for uncomfortable stretches by design. The benchmark comparison in §8 needs a multi-year lens.
- Output is a research process and thesis journal, not financial advice; position sizing and the final buy decision stay human.
