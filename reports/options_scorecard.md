# Options pre-registration scorecard — through 2026-08-03

274 resolved events; 16 carried registered structures (entries frozen at registration prices — buy at ask / sell at bid).

## Calibration (all resolved events)
- realized |move| landed inside the frozen implied move in **82%** of events (vol premium says this should exceed ~50%)
- median realized/implied: **0.49** · median realized/fair: **0.88**

## Structure P&L (expiry settlement, 1 contract per registration)
- **3/16 winners · net P&L $-2,252** (gross credits/debits $8,376)

| Ticker | Event | Structure | Implied | Realized | P&L |
|---|---|---|---|---|---|
| XOM | 2026-07-31 BMO | iron fly | ±4.6% | -1.0% | $162 |
| BAC | 2026-07-14 BMO | iron fly | ±3.7% | +1.9% | $66 |
| F | 2026-07-28 AMC | iron fly | ±7.6% | +2.1% | $25 |
| BA | 2026-07-28 BMO | iron fly | ±6.8% | +4.8% | $-89 |
| T | 2026-07-22 BMO | iron fly | ±4.9% | +3.5% | $-109 |
| CMG | 2026-07-29 AMC | iron fly | ±10.1% | +12.5% | $-120 |
| COIN | 2026-07-30 AMC | iron fly | ±13.2% | -10.6% | $-120 |
| C | 2026-07-14 BMO | iron fly | ±4.5% | -5.3% | $-211 |
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
| cheap (model: long vol) | 4 | $-148 | $-367 | $-367 |
| neutral (model: no trade) | 17 | $-2,077 | $-149 | $0 |
| rich (model: short vol) | 114 | $14,533 | $-42,865 | $14,533 |

- **Model-aligned total: $14,166** vs always-short-everything $12,308 (n=135)
- Screened events are included: the screen protects fills, not signal scoring.

| ISO week | short-all P&L | model-aligned P&L |
|---|---|---|
| 29 | $2,443 | $1,633 |
| 30 | $-9,325 | $-5,736 |
| 31 | $19,190 | $18,269 |

_Directional evidence, not a verdict (plan §4): hypothetical fills at frozen_
_delayed quotes flatter both sides. Season-end review adds calibration bands,_
_edge-vs-P&L regression, and the cost-drag reality check._