# Options pre-registration scorecard — through 2026-07-29

154 resolved events; 7 carried registered structures (entries frozen at registration prices — buy at ask / sell at bid).

## Calibration (all resolved events)
- realized |move| landed inside the frozen implied move in **80%** of events (vol premium says this should exceed ~50%)
- median realized/implied: **0.49** · median realized/fair: **0.83**

## Structure P&L (expiry settlement, 1 contract per registration)
- **1/7 winners · net P&L $-1,199** (gross credits/debits $3,141)

| Ticker | Event | Structure | Implied | Realized | P&L |
|---|---|---|---|---|---|
| BAC | 2026-07-14 BMO | iron fly | ±3.7% | +1.9% | $66 |
| T | 2026-07-22 BMO | iron fly | ±4.9% | +3.5% | $-109 |
| C | 2026-07-14 BMO | iron fly | ±4.5% | -5.3% | $-211 |
| GOOG | 2026-07-22 AMC | iron fly | ±7.0% | -6.9% | $-220 |
| INTC | 2026-07-23 AMC | iron fly | ±15.9% | -7.9% | $-240 |
| GOOGL | 2026-07-22 AMC | iron fly | ±7.1% | -7.1% | $-240 |
| NOW | 2026-07-22 AMC | iron fly | ±13.1% | -3.7% | $-245 |

## Signal validity — hypothetical 1-lot straddles at frozen quotes

Sell-at-bid / buy-at-ask for EVERY resolved event, grouped by what the
model said at registration. If the edge signal is real, rich events should
make money shorted and cheap events should make money bought.

| Model bucket | n | short-straddle P&L | long-straddle P&L | model-aligned P&L |
|---|---|---|---|---|
| cheap (model: long vol) | 3 | $-142 | $-352 | $-352 |
| neutral (model: no trade) | 11 | $-2,989 | $1,584 | $0 |
| rich (model: short vol) | 53 | $-3,680 | $-8,734 | $-3,680 |

- **Model-aligned total: $-4,032** vs always-short-everything $-6,811 (n=67)
- Screened events are included: the screen protects fills, not signal scoring.

| ISO week | short-all P&L | model-aligned P&L |
|---|---|---|
| 29 | $2,514 | $1,704 |
| 30 | $-9,325 | $-5,736 |

_Directional evidence, not a verdict (plan §4): hypothetical fills at frozen_
_delayed quotes flatter both sides. Season-end review adds calibration bands,_
_edge-vs-P&L regression, and the cost-drag reality check._