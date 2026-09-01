# Options pre-registration scorecard — through 2026-09-01

460 resolved events; 29 carried registered structures (entries frozen at registration prices — buy at ask / sell at bid).

## Calibration (all resolved events)
- realized |move| landed inside the frozen implied move in **67%** of events (vol premium says this should exceed ~50%)
- median realized/implied: **0.46** · median realized/fair: **0.84**

## Structure P&L (expiry settlement, 1 contract per registration)
- **9/29 winners · net P&L $-2,602** (gross credits/debits $13,379)

| Ticker | Event | Structure | Implied | Realized | P&L |
|---|---|---|---|---|---|
| MRVL | 2026-08-27 AMC | iron fly | ±15.1% | -10.3% | $427 |
| OKE | 2026-08-03 AMC | iron fly | ±7.7% | -0.7% | $193 |
| Q | 2026-08-04 BMO | iron fly | ±21.2% | +6.3% | $178 |
| OXY | 2026-08-05 AMC | iron fly | ±7.2% | +4.1% | $87 |
| APH | 2026-07-29 BMO | iron fly | ±14.5% | +4.5% | $69 |
| BAC | 2026-07-14 BMO | iron fly | ±3.7% | +1.9% | $66 |
| XOM | 2026-07-31 BMO | iron fly | ±4.6% | -1.0% | $62 |
| F | 2026-07-28 AMC | iron fly | ±7.6% | +2.1% | $41 |
| NVDA | 2026-08-26 AMC | iron fly | ±7.3% | +8.7% | $35 |
| O | 2026-08-05 AMC | iron fly | ±4.1% | -0.5% | $-85 |
| SMCI | 2026-08-04 AMC | iron fly | ±19.8% | -4.3% | $-104 |
| COIN | 2026-07-30 AMC | iron fly | ±13.2% | -10.6% | $-120 |
| CMG | 2026-07-29 AMC | iron fly | ±10.1% | +12.5% | $-120 |
| ADM | 2026-08-04 BMO | iron fly | ±8.5% | +2.3% | $-130 |
| EXE | 2026-07-28 AMC | iron fly | ±8.3% | +4.5% | $-160 |
| LYB | 2026-07-31 BMO | iron fly | ±11.8% | +2.7% | $-165 |
| MNST | 2026-08-06 AMC | iron fly | ±8.0% | +91.9% | $-170 |
| CRM | 2026-08-26 AMC | iron fly | ±9.6% | +22.6% | $-185 |
| SWKS | 2026-07-28 AMC | iron fly | ±17.5% | -5.4% | $-209 |
| C | 2026-07-14 BMO | iron fly | ±4.5% | -5.3% | $-211 |
| PLTR | 2026-08-03 AMC | iron fly | ±13.4% | +29.5% | $-220 |
| GOOG | 2026-07-22 AMC | iron fly | ±7.0% | -6.9% | $-220 |
| AMZN | 2026-07-30 AMC | iron fly | ±7.7% | +15.3% | $-220 |
| HOOD | 2026-07-29 AMC | iron fly | ±12.9% | -3.6% | $-226 |
| INTC | 2026-07-23 AMC | iron fly | ±15.9% | -7.9% | $-240 |
| GOOGL | 2026-07-22 AMC | iron fly | ±7.1% | -7.1% | $-240 |
| GPN | 2026-08-05 BMO | iron fly | ±12.2% | -0.9% | $-245 |
| NOW | 2026-07-22 AMC | iron fly | ±13.1% | -3.7% | $-245 |
| AAPL | 2026-07-30 AMC | iron fly | ±5.3% | -7.4% | $-245 |

## Signal validity — hypothetical 1-lot straddles at frozen quotes

Sell-at-bid / buy-at-ask for EVERY resolved event, grouped by what the
model said at registration. If the edge signal is real, rich events should
make money shorted and cheap events should make money bought.

| Model bucket | n | short-straddle P&L | long-straddle P&L | model-aligned P&L |
|---|---|---|---|---|
| cheap (model: long vol) | 8 | $-920 | $-282 | $-282 |
| neutral (model: no trade) | 26 | $-1,173 | $-4,622 | $0 |
| rich (model: short vol) | 336 | $115,335 | $-245,751 | $115,335 |

- **Model-aligned total: $115,053** vs always-short-everything $113,243 (n=370)
- Screened events are included: the screen protects fills, not signal scoring.

| ISO week | short-all P&L | model-aligned P&L |
|---|---|---|
| 29 | $-1,132 | $-2,021 |
| 30 | $14,260 | $17,776 |
| 31 | $68,957 | $71,700 |
| 32 | $40,679 | $35,963 |
| 33 | $-13,130 | $-13,102 |
| 34 | $2,001 | $3,130 |
| 35 | $1,607 | $1,607 |

_Directional evidence, not a verdict (plan §4): hypothetical fills at frozen_
_delayed quotes flatter both sides. Season-end review adds calibration bands,_
_edge-vs-P&L regression, and the cost-drag reality check._