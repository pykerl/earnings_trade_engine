# plan_reddit_growth.md — Creative Growth Positions from Reddit Signal + Constraint Mapping (Free Data)

Goal: a pipeline that uses Reddit stock picks (r/wallstreetbets 2025 & 2026 cohorts + live mention flow) as an **idea funnel and crowding gauge — never a buy signal** — then does the creative work the crowd doesn't: mapping each crowded theme to its **physical supply-chain bottlenecks** (semis, memory/HBM, AI datacenter power/cooling/optics, robotics actuators) and surfacing the under-owned constraint owners. Output: researched position ideas where the **"why" memo** explains what Reddit sees, what Reddit misses, and why a specific node captures the value.

Companion to `plan_free_weekend.md` (options engine) and `plan_value.md` (quality/valuation gates) — this plan reuses modules from both.

---

## 0. Thesis of the plan itself

Three claims this pipeline is built to exploit and test:

1. **Reddit is a decent scout, a bad allocator.** The WSB 2025 crowd portfolio returned ~76%, and the 2026 index (ASTS, RKLB, GOOGL, AMZN, NBIS, RDDT, MU, IREN, TSLA, PLTR; upvote variants add POET, SOFI, PATH) shows the crowd migrating from meme squeezes to genuine technology themes: space, AI infrastructure, memory, optics, automation. The themes are often right; the specific tickers are crowded and momentum-priced by the time they chart on WSB.
2. **The alpha migrates upstream.** When a theme is consensus (AI datacenters), the first-order names get bid first (NVDA → hyperscalers → NBIS/IREN). The physical constraints that gate the whole theme — HBM supply, advanced packaging capacity, grid interconnection, transformers, liquid cooling, optical interconnects, and for robotics: actuators, harmonic drives/precision reducers, encoders, rare-earth magnets — reprice later and less completely. The creative engine's job is to walk the supply-chain graph from crowded node to constrained-but-quiet node.
3. **Crowding is measurable and mean-reverting at extremes.** Reddit mention velocity + short interest + valuation-vs-growth gives a crowding score usable both as an entry filter (avoid buying the top of retail attention) and as an input to engine #1 (crowded names → elevated IV → defined-risk options structures instead of stock).

All three are hypotheses, and section 7 tests them rather than assuming them.

---

## 1. Free data source map

| Need | Source | Notes |
|---|---|---|
| WSB 2025 & 2026 pick cohorts | The annual index threads + press summaries; hardcode the two cohorts into `config/cohorts.yaml` as ground truth | 2026 index: ASTS, RKLB, GOOGL, AMZN, NBIS, RDDT, MU, IREN, TSLA, PLTR; log the upvote-list variant too |
| Live Reddit mentions/sentiment | Reddit official API via PRAW (free OAuth tier, 100 req/min) on r/wallstreetbets, r/stocks, r/investing, r/hardware; **ApeWisdom free API** for pre-aggregated ticker mention counts | ApeWisdom saves enormous scraping effort — daily mentions + rank per ticker, free JSON |
| Historical prices for cohort autopsy | yfinance (reuse `ingest/prices.py`) | |
| Fundamentals / dilution / survivability | EDGAR companyfacts (reuse the entire `plan_value` metric layer) | |
| Short interest | FINRA short interest files (free, biweekly) | Crowding score input |
| Supply-chain / constraint evidence | Web research performed by Claude Code with citations: earnings call remarks, company 10-K supplier/customer disclosures (EDGAR full-text), capex announcements, trade press | This is deliberately agentic research, not an API — the constraint map is curated, sourced YAML, not scraped |
| Earnings calendar | Reuse `ingest/calendar.py` | For timing notes on candidates |
| Foreign-listed constraint owners (e.g., Japanese actuator makers) | yfinance handles Tokyo tickers (e.g., `6324.T`) and ADRs | Flag liquidity/ADR access in memos |

---

## 2. Stage A — Cohort autopsy (was the 76% skill?)

Before trusting the funnel, dissect it:

- Reconstruct WSB 2025 and 2026 cohorts as equal-weight portfolios from list-publication date; compute total return vs SPY and QQQ, max drawdown, hit rate, and **contribution concentration** (was it 2 winners carrying 8 losers?).
- Decompose: how much return is explained by beta + momentum exposure (regress cohort on market + momentum factor from free Fama-French files) vs unexplained residual? A 76% year in a strong tape is different from 76% of stock-picking skill.
- Entry-timing sensitivity: returns if bought 1 week / 1 month / 3 months after publication — measures how much of the move is already gone by the time the crowd publishes (this number directly calibrates how to use the live mention feed).
- Q2 2026 checkpoint: score the 2026 cohort year-to-date (the exercise from the WSB thread that seeded this plan), name by name, with the same decomposition.

Deliverable: `reports/cohort_autopsy.md` — the empirical answer to "should Reddit be in the funnel at all," with effect sizes.

---

## 3. Stage B — Theme extraction & the constraint map (the creative core)

**B1. Theme clustering:** classify every cohort/high-mention ticker into growth themes (AI compute, AI datacenter infra, memory, optics/networking, space, robotics/automation, fintech). Simple curated mapping table, not NLP — 50 tickers don't need a model.

**B2. Constraint graph:** for each theme, build `config/constraint_map.yaml` — a curated, citation-backed graph of the physical bottlenecks, researched agentically. Seed hypotheses to verify and extend with current (July 2026) sources:

- **AI compute → memory:** HBM supply and yields; advanced packaging (CoWoS-class) capacity. Note: the crowd already found MU — the question is which adjacent nodes (equipment, materials, testing) remain quiet.
- **AI datacenter → power:** grid interconnection queues, gas turbines, transformers, switchgear, backup power, electrical construction. Which listed names own the multi-year backlogs?
- **AI datacenter → cooling:** liquid/direct-to-chip cooling supply chain.
- **AI datacenter → networking/optics:** optical transceivers, photonics (crowd found POET — map the rest of the chain), high-speed interconnect components.
- **Robotics → actuation:** harmonic drives / precision reducers (largely Japan-listed), servo motors, encoders, force/torque sensors, rare-earth magnets and their processing chokepoints.
- **Space (ASTS/RKLB adjacency):** launch components, RF/phased-array suppliers, if evidence supports a real bottleneck.

Each node in the YAML carries: what the constraint is, evidence with sources (earnings-call statements about lead times/backlogs, capex announcements, pricing actions), listed pure-plays and diversified players with revenue-exposure estimates, and **who else has already found it** (the crowding inputs).

**B3. Crowding score per node:** z-scores of Reddit mention velocity (ApeWisdom trailing 30d vs 180d), short interest, and EV/S vs revenue growth percentile within theme. High theme conviction + low node crowding = the target quadrant.

---

## 4. Stage C — Validation gates (borrowed from plan_value, tuned for growth)

Growth names won't pass Buffett gates; use survivability + quality-of-growth instead:

- **Survivability:** cash runway > 8 quarters at current burn (or FCF positive); net debt/EBITDA sane for profitable names; no going-concern language (EDGAR scan).
- **Quality of growth:** revenue growth + FCF margin (rule-of-40 style, applied loosely), gross margin trend, backlog/RPO growth where disclosed, customer concentration flags.
- **Dilution discipline:** share count CAGR and SBC as % of revenue — the classic way retail growth darlings quietly transfer returns away from holders.
- **Evidence gate (the important one):** at least two independent, dated, cited pieces of evidence that the constraint is real and the company is a genuine beneficiary (backlog numbers, lead-time statements, price increases, capacity sold out). No evidence, no candidacy — vibes are what the funnel is for, not what positions are built on.

---

## 5. Stage D — Creative position construction (three sleeves)

For each surviving idea, propose the *structure* that fits the thesis, sized for the $10k research book and paper-traded first:

1. **Quiet constraint owner, direct equity:** the core sleeve — under-crowded node, validated fundamentals, buy-and-hold with thesis-based (not price-based) exit conditions.
2. **Crowded name, defined-risk options expression:** when the right exposure is a crowded WSB name (e.g., MU into an HBM-driven print), route it through engine #1 — elevated IV and crowding often make verticals/calendars better-shaped than stock; max loss ≤ $250 rules inherited from `plan_free_weekend.md`.
3. **Barbell/pair:** long quiet constraint node vs. avoiding (or structurally underweighting) the crowded first-order expression of the same theme — captures the "alpha migrates upstream" claim directly and hedges theme-level drawdown.

Portfolio rules: max 3 themes active, max 2 positions per theme, single-name max risk 5% of book, foreign-listed names flagged for access/liquidity, everything enters the same pre-registration journal as the other engines.

---

## 6. The "why" memo (per idea) — the deliverable

Template, one page, git-versioned like the value memos:

1. **The theme and where Reddit is** — which cohort/mention signal surfaced it; current crowding scores of the obvious names.
2. **The constraint** — the physical bottleneck, with dated cited evidence (the research core).
3. **Why this node** — revenue exposure to the constraint, competitive position, who else supplies it, what capacity additions are coming (the thesis-killer to watch).
4. **What the crowd misses** — the explicit creative claim: why this is mispriced relative to the first-order names.
5. **Validation gate results** — survivability, quality-of-growth, dilution numbers.
6. **Structure & sizing** — which sleeve, why that structure, max loss.
7. **Pre-mortem & exit conditions** — what evidence would falsify the constraint thesis (capacity coming online, design-outs, demand air pocket); these are the exit triggers, pre-registered.
8. **Earnings note** — when it reports; what one print can/can't confirm.

---

## 7. Measurement (same discipline as the other engines)

- **Funnel value test:** does the Reddit funnel + constraint mapping produce candidates that outperform (a) the raw WSB cohort and (b) QQQ, cohort-by-cohort? Track from memo date, paper first.
- **Crowding signal test:** do high-crowding scores predict worse forward returns in this universe? (This validates or kills the contrarian layer.)
- **Evidence-gate audit:** for every position, did the pre-registered thesis evidence strengthen or weaken at each subsequent print? Thesis journal, scored quarterly.
- **Honest bar:** one or two seasons of cohorts is directional evidence only; the cohort autopsy (Stage A) is the only part with enough history to be statistically meaningful at launch.

## 8. Honest limitations

- Academic evidence on retail-attention signals is genuinely mixed — attention spikes predict short-term momentum and longer-term reversal. That's exactly why crowding is a filter here, not a factor bet.
- The 2025 cohort's ~76% came in a strong growth tape; Stage A's factor decomposition exists to keep that number from flattering the funnel.
- The constraint map is curated research, not data — it can be wrong, stale, or already priced. The two-source dated-evidence gate and capacity-watch exit triggers are the defenses.
- Several of the best actuator/reducer plays are Japan-listed with thin ADRs; access and FX are real frictions, memo-flagged.
- Supply constraints resolve — capacity gets built. These are 1–3 year theses with expiry dates, not Buffett holds; the pre-mortem section is load-bearing.
- Research process, not financial advice; paper-first like everything else in this stack.

---

## Appendix: Claude Code prompt

```
Read plan_reddit_growth.md in full before writing any code — it is the spec. This repo reuses
modules from the options repo (plan_free_weekend) and value repo (plan_value); copy or import
ingest/prices.py, ingest/calendar.py, and the EDGAR fundamentals + quality metric layer rather
than rewriting them.

Build in this order, committing after each working step:

1. Scaffold: ingest/, autopsy/, themes/, constraints/, gates/, positions/, memos/, journal/,
   config/. Python 3.11. Env vars: REDDIT_CLIENT_ID, REDDIT_CLIENT_SECRET, REDDIT_USER_AGENT,
   plus the existing ALPHAVANTAGE/FINNHUB/FRED/SEC vars.
2. config/cohorts.yaml — hardcode the WSB 2025 and 2026 cohorts with publication dates and
   sources (2026 index: ASTS, RKLB, GOOGL, AMZN, NBIS, RDDT, MU, IREN, TSLA, PLTR; also store
   the upvote-list variant incl. POET, SOFI, PATH). Verify the 2025 list by web search and cite.
3. autopsy/cohorts.py — Stage A in full: equal-weight cohort returns vs SPY/QQQ from publication
   date, contribution concentration, entry-lag sensitivity (0/1wk/1mo/3mo), and factor
   decomposition using the free Fama-French daily factor file. Output reports/cohort_autopsy.md
   with every number. Do this BEFORE any idea generation — it calibrates the funnel.
4. ingest/mentions.py — ApeWisdom API for daily ticker mentions (with graceful failure), plus a
   PRAW-based fallback sampler for r/wallstreetbets daily threads. Store trailing mention
   velocity (30d vs 180d z-score).
5. themes/cluster.py — curated ticker→theme mapping table for the cohort + top-100 mention
   universe.
6. constraints/ — this is agentic research, not scraping: for each theme in section 3.B2,
   research current (July 2026) supply bottlenecks via web search and EDGAR full-text, and write
   config/constraint_map.yaml with the schema in the plan: constraint description, >=2 dated
   cited evidence items per node, listed pure-plays and diversified players with rough revenue
   exposure, crowding inputs. Every claim needs a source URL and date. Present the draft map to
   me for review before building on it.
7. gates/growth_gates.py — section 4 validation gates using the value repo's EDGAR layer:
   runway, rule-of-40, gross margin trend, dilution/SBC, going-concern scan, and the
   two-source evidence gate (reads from constraint_map.yaml).
8. positions/construct.py — three-sleeve logic from section 5 with the portfolio rules encoded;
   options-sleeve candidates get exported in the format engine #1's dashboard expects rather
   than re-implementing options logic here.
9. memos/generator.py — the eight-section memo from section 6, jinja2, git-versioned, evidence
   citations inline, [FOR HUMAN REVIEW] markers on all qualitative claims.
10. journal/ — pre-registration writer shared-format with the other repos: thesis evidence
    expectations + exit triggers, append-only.
11. Entrypoint `make ideas`: refresh mentions, rescore crowding, re-run gates, regenerate the
    ranked idea dashboard (HTML+CSV) and memos for the top 8.

Constraints:
- Free data only. Respect Reddit API ToS (official OAuth only, no scraping around it) and SEC
  rate limits with proper User-Agent.
- The cohort autopsy (step 3) and constraint map review (step 6) are hard checkpoints — stop
  and show me results at each before continuing.
- No trading execution of any kind; research memos, dashboard, and paper journal only.
- Every constraint claim in the YAML must have a dated source; anything unsourced gets
  needs_evidence: true and is excluded from gating.
- If ApeWisdom or Reddit auth is unavailable, degrade gracefully to cohort-only mode and tell me.

Deliverable by end of session: reports/cohort_autopsy.md with the 2025/2026 numbers, a reviewed
constraint_map.yaml, and `make ideas` producing a ranked dashboard + top-8 memos.
```
