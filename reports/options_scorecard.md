# Options pre-registration scorecard — through 2026-08-19

433 resolved events; 19 carried registered structures (entries frozen at registration prices — buy at ask / sell at bid).

## Calibration (all resolved events)
- realized |move| landed inside the frozen implied move in **78%** of events (vol premium says this should exceed ~50%)
- median realized/implied: **0.47** · median realized/fair: **0.83**

## Structure P&L (expiry settlement, 1 contract per registration)
- **4/19 winners · net P&L $-2,573** (gross credits/debits $9,498)

| Ticker | Event | Structure | Implied | Realized | P&L |
|---|---|---|---|---|---|
| OXY | 2026-08-05 AMC | iron fly | ±7.2% | +4.1% | $87 |
| BAC | 2026-07-14 BMO | iron fly | ±3.7% | +1.9% | $66 |
| XOM | 2026-07-31 BMO | iron fly | ±4.6% | -1.0% | $62 |
| F | 2026-07-28 AMC | iron fly | ±7.6% | +2.1% | $41 |
| BA | 2026-07-28 BMO | iron fly | ±6.8% | +4.8% | $-89 |
| SMCI | 2026-08-04 AMC | iron fly | ±19.8% | -4.3% | $-104 |
| T | 2026-07-22 BMO | iron fly | ±4.9% | +3.5% | $-109 |
| CMG | 2026-07-29 AMC | iron fly | ±10.1% | +12.5% | $-120 |
| COIN | 2026-07-30 AMC | iron fly | ±13.2% | -10.6% | $-120 |
| C | 2026-07-14 BMO | iron fly | ±4.5% | -5.3% | $-211 |
| PLTR | 2026-08-03 AMC | iron fly | ±13.4% | +29.5% | $-220 |
| GOOG | 2026-07-22 AMC | iron fly | ±7.0% | -6.9% | $-220 |
| AMZN | 2026-07-30 AMC | iron fly | ±7.7% | +15.3% | $-220 |
| META | 2026-07-29 AMC | iron fly | ±10.0% | -8.0% | $-220 |
| HOOD | 2026-07-29 AMC | iron fly | ±12.9% | -3.6% | $-226 |
| INTC | 2026-07-23 AMC | iron fly | ±15.9% | -7.9% | $-240 |
| GOOGL | 2026-07-22 AMC | iron fly | ±7.1% | -7.1% | $-240 |
| NOW | 2026-07-22 AMC | iron fly | ±13.1% | -3.7% | $-245 |
| AAPL | 2026-07-30 AMC | iron fly | ±5.3% | -7.4% | $-245 |

## Signal validity — hypothetical 1-lot straddles at frozen quotes

Sell-at-bid / buy-at-ask for EVERY resolved event, grouped by what the
model said at registration. If the edge signal is real, rich events should
make money shorted and cheap events should make money bought.

| Model bucket | n | short-straddle P&L | long-straddle P&L | model-aligned P&L |
|---|---|---|---|---|
| cheap (model: long vol) | 7 | $-842 | $-315 | $-315 |
| neutral (model: no trade) | 22 | $6,525 | $-10,522 | $0 |
| rich (model: short vol) | 171 | $26,516 | $-77,357 | $26,516 |

- **Model-aligned total: $26,201** vs always-short-everything $32,200 (n=200)
- Screened events are included: the screen protects fills, not signal scoring.

| ISO week | short-all P&L | model-aligned P&L |
|---|---|---|
| 29 | $2,510 | $1,621 |
| 30 | $-9,262 | $-5,671 |
| 31 | $22,934 | $22,593 |
| 32 | $29,567 | $21,207 |
| 33 | $-13,549 | $-13,549 |

_Directional evidence, not a verdict (plan §4): hypothetical fills at frozen_
_delayed quotes flatter both sides. Season-end review adds calibration bands,_
_edge-vs-P&L regression, and the cost-drag reality check._