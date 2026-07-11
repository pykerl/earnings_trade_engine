# plan_free_weekend.md — Earnings Alpha Engine, Free-Data Edition

Goal: a working, ranked earnings-options dashboard by **Sunday night (July 12, 2026)**, using only free data, in time for Q2 earnings season (banks kick it off the week of July 13). Q2 season itself becomes the out-of-sample forward test that answers "how well does this do with free datasets."

This is a descoped fork of `plan.md`. Same statistical philosophy, radically triaged execution.

---

## 1. What survives, what gets cut, what gets replaced

| Full-plan component | Weekend free-data status |
|---|---|
| 15-yr historical options backtest | **CUT** (no free bulk options history). Replaced by: (a) literature-informed priors, (b) slow Alpha Vantage backfill, (c) **Q2 forward test as the real validation** |
| Hierarchical-Bayes fair-move model | **KEPT IN FULL** — needs only free equity OHLCV + historical earnings dates |
| Implied move from live chains | **KEPT** — yfinance option chains (delayed, good enough for EOD signals) |
| Ownership/positioning features (13F, short interest) | **DEFERRED to v2** — SEC EDGAR + FINRA are free but parsing eats the weekend |
| Dealer gamma, IV surface fitting | **CUT for v1** — ATM straddle mid is the only IV object we need |
| Pre-registered hypothesis tests | **KEPT, forward-looking** — register predictions before each event, score after |
| Promotion gates / paper trading first | **KEPT** — Q2 is paper-only (or trivially small pilot); no real sizing until the season-end review |
| Daily ranked dashboard | **KEPT** — the weekend deliverable |

**The core insight that makes the weekend feasible:** the fair side of the trade (what *should* the earnings move be?) requires zero options data — just each name's historical realized earnings-day moves, computable from free daily OHLCV + earnings dates. The market side (what is the option market *implying*?) only needs today's chain. Edge = implied − fair. Free data covers both.

---

## 2. Free data source map

| Need | Source | Notes / gotchas |
|---|---|---|
| Earnings calendar (next 2–3 weeks) | `yfinance` earnings dates; cross-check Finnhub free tier + Nasdaq calendar page | yfinance dates are sometimes wrong or lack BMO/AMC; **cross-validate 2 sources, drop names that disagree** |
| Historical earnings dates (5–10 yrs) | yfinance `get_earnings_dates()` (limited depth) + backfill from Alpha Vantage `EARNINGS` endpoint | AV free key: 25 req/day, 5/min — one ticker per call, so backfill drips over days; start with the ~60 names reporting in the next 3 weeks |
| Daily OHLCV, 15+ yrs, splits/divs | yfinance bulk download | Free, reliable, fast; the workhorse |
| Current option chains (bid/ask, IV, OI, vol) | yfinance `option_chain()` per expiry | 15-min delayed quotes — fine for an EOD process; pull after close |
| S&P 500 membership | Wikipedia constituents table (current) | Point-in-time history not free-easy; acceptable for a forward test (no backtest = no survivorship problem) |
| Historical options (spot-check backfill) | Alpha Vantage `HISTORICAL_OPTIONS` — free tier includes historical options data at 25 requests/day, 5/min | 1 call = 1 ticker-date full chain. Budget: nightly cron burns the 25-call ration backfilling T-1 chains for past earnings of your top-ranked names. Slow drip, compounds into a real validation set over weeks |
| Earnings surprise history | Alpha Vantage `EARNINGS` (EPS est vs actual) | Same 25/day ration; queue behind options backfill or use a second free key is against ToS — don't |
| Risk-free rate | FRED (free API) or hardcode 3M T-bill weekly | Only needed if computing greeks; v1 doesn't |
| Short interest / 13F (v2) | FINRA short interest files; SEC EDGAR full-text 13F | Free, deferred |

**Rate-limit budget (Alpha Vantage, 25/day):** treat calls as the scarcest resource. Priority order: (1) earnings-date backfill for names reporting within 10 days, (2) historical T-1 chains for those same names' past 8 quarters → builds the implied-move history that free sources can't give you in bulk. At 25/day you accumulate ~175 ticker-event-days per week; by the end of Q2 season you'll have a few hundred genuine historical implied-vs-realized observations. That's the "how well would this have done" dataset, growing in the background.

---

## 3. Weekend build schedule

### Saturday — data + model (target: fair-move model working by dinner)

**Block 1 (3–4 hrs): ingestion**
- `ingest/calendar.py`: pull next-21-day earnings calendar (yfinance + Finnhub cross-check), keep S&P 500 names only, flag BMO/AMC where known. Output: `events_upcoming.parquet`.
- `ingest/prices.py`: bulk-download 15 yrs daily OHLCV for the full S&P 500 (one yfinance batch call, ~10 min). Output: `prices.parquet`.
- `ingest/earnings_history.py`: yfinance historical earnings dates per upcoming-reporter; queue Alpha Vantage backfill for names with thin history.

**Block 2 (3–4 hrs): realized-move engine + fair model**
- `features/moves.py`: for each (ticker, past earnings date): compute earnings-day move correctly for BMO (that day's open gap + day move) vs AMC (next day's move). Where BMO/AMC unknown, take max(|day|, |next-day|) and flag lower confidence.
- `model/fair_move.py`: hierarchical shrinkage estimate of expected |move| per name:
  - name-level: mean/median of last 8–12 quarterly |moves|, recency-weighted
  - pool-level: sector × market-cap-bucket average
  - blend weight by name-level sample size (empirical-Bayes shrinkage: `w = n/(n+k)`, k≈6)
  - also fit a scaled-t to each name's standardized moves for the tail model (used for EV of long-vol structures)
- Sanity harness: fair-move estimates vs each name's actual most recent move — eyeball the calibration.

### Sunday — signal + dashboard (target: ranked output by evening)

**Block 3 (2–3 hrs): implied side**
- `ingest/chains.py`: after Saturday close data is set, pull chains for every name reporting in the next 10 trading days; select the expiry immediately after the event.
- Implied move = ATM straddle **mid** ÷ spot (also record it at the ask — your realistic entry cost as a buyer, and at the bid as a seller). Record spread %, OI, volume.
- Liquidity screen: drop names where ATM straddle spread > 8–10% of straddle value or OI < 500 on the event expiry. **Expect this to kill a third of the list — that's the model working, not failing.**

**Block 4 (3–4 hrs): scoring + dashboard + logging**
- `scoring/rank.py`: edge = (implied − fair) / fair, with a rough CI from the name's move-sample size. v1 score = edge z-score × liquidity multiplier × confidence multiplier. No ML, no 11-factor blend — that comes back in v2 when there's data to fit it on.
- Strategy mapping (defined-risk only, $10k paper account):
  - implied ≫ fair (rich): **iron fly / iron condor**, wings sized so max loss ≤ $250
  - implied ≪ fair (cheap): **long straddle/strangle**, debit ≤ $250
  - |edge| small: **no trade** (the default state)
- `dashboard/daily.py`: ranked HTML + CSV with: ticker, earnings date/time, implied move (mid & ask), fair move ± CI, edge %, structure, max gain/loss, spread cost as % of edge, confidence, sample size, flags.
- **Pre-registration log (`log/predictions.csv`)**: every event gets a frozen row *before* it reports — fair move, implied move, chosen structure, hypothetical entry at realistic prices (buy at ask, sell at bid). This file is the experiment.

---

## 4. How "how well does it do" gets measured (Q2 = the test)

Run daily through the season (~15 min/day: refresh chains after close, log fills next day). At season end (~early September):

1. **Calibration:** were realized |moves| consistent with the fair-move distributions? (PIT histogram; % of moves inside predicted 50%/80% bands.)
2. **Signal validity:** did high-edge events deliver? Regress realized straddle P&L (at logged realistic prices) on edge score. This is the one number that matters.
3. **Paper P&L:** portfolio-level result under the position rules, vs SPY over the same window — with the honest caveat that one season ≈ 100–300 events is enough to judge calibration and directional signal validity, **not** enough to prove long-run alpha.
4. **Cost reality check:** measured spread drag vs assumed. If crossing the spread eats >60–70% of median gross edge, the free-data verdict is "signal maybe, monetization no" — also a valid result.
5. **Backfill check:** by then the Alpha Vantage drip has built a few-hundred-event historical implied-move set → run the same edge score retrospectively as a pseudo-backtest.

Promotion decision after the season: real (small) capital only if calibration passes AND edge-P&L relationship is positive AND cost drag is survivable. Otherwise iterate to v2 (ownership features, better data) or accept the null.

---

## 5. Honest limitations of the free build

- **No historical IV = no backtest at launch.** The Q2 forward test is a single regime, single season. Treat any result — good or bad — as one data point.
- yfinance chains are delayed and occasionally stale; mid-quotes on illiquid names are fiction. The liquidity screen and log-at-bid/ask convention are the defenses.
- Earnings timestamps (BMO/AMC) from free sources are unreliable ~5–10% of the time; a wrong timestamp corrupts that event's realized-move label. Cross-check two sources; drop conflicts.
- The best-attested edge (short earnings vol premium) expressed as defined-risk structures on a $10k account faces exactly the spread-drag problem that free/delayed quotes make hardest to measure — which is why nothing goes live on this build's say-so alone.
- yfinance is an unofficial API; endpoints break without notice. Keep ingestion modular so a source swap is a one-file fix.

## 6. v2 backlog (post-season, in priority order)
1. FINRA short interest + EDGAR 13F features (free, just parsing work)
2. Continue AV historical-options accumulation → real mini-backtest
3. Term-structure/calendar signals (needs 2 expiries per name — doubles chain pulls, still free via yfinance)
4. Re-introduce the full scoring blend from `plan.md` once there's OOS data to fit weights on
