# Options pre-registration scorecard — through 2026-07-20

22 resolved events; 2 carried registered structures (entries frozen at registration prices — buy at ask / sell at bid).

## Calibration (all resolved events)
- realized |move| landed inside the frozen implied move in **59%** of events (vol premium says this should exceed ~50%)
- median realized/implied: **0.90** · median realized/fair: **1.08**

## Structure P&L (expiry settlement, 1 contract per registration)
- **1/2 winners · net P&L $-145** (gross credits/debits $582)

| Ticker | Event | Structure | Implied | Realized | P&L |
|---|---|---|---|---|---|
| BAC | 2026-07-14 BMO | iron fly | ±3.7% | +1.9% | $66 |
| C | 2026-07-14 BMO | iron fly | ±4.5% | -5.3% | $-211 |

## Signal validity — hypothetical 1-lot straddles at frozen quotes

Sell-at-bid / buy-at-ask for EVERY resolved event, grouped by what the
model said at registration. If the edge signal is real, rich events should
make money shorted and cheap events should make money bought.

| Model bucket | n | short-straddle P&L | long-straddle P&L | model-aligned P&L |
|---|---|---|---|---|
| neutral (model: no trade) | 6 | $810 | $-1,566 | $0 |
| rich (model: short vol) | 16 | $1,795 | $-5,969 | $1,795 |

- **Model-aligned total: $1,795** vs always-short-everything $2,605 (n=22)
- Screened events are included: the screen protects fills, not signal scoring.

_Directional evidence, not a verdict (plan §4): hypothetical fills at frozen_
_delayed quotes flatter both sides. Season-end review adds calibration bands,_
_edge-vs-P&L regression, and the cost-drag reality check._