# earnings_trade_engine (v1, free-data edition)

Ranked earnings-options dashboard built exactly to `plan_free_weekend.md`
(sections 2–3). Free data only: yfinance + Wikipedia + Nasdaq calendar, with a
rationed Alpha Vantage backfill drip. Paper/logging only — no broker, no live
trading.

## Quick start

```bash
make setup                          # uv sync (Python 3.11)
export ALPHAVANTAGE_API_KEY=...     # optional; enables the backfill drip
make daily                          # full pipeline -> data/dashboard/ + log/predictions.csv
```

`make daily` refreshes option chains, rescores, rewrites the dashboard
(HTML + CSV under `data/dashboard/`), and appends frozen pre-registration rows
to `log/predictions.csv` (append-only; rows are never rewritten). Slow inputs
(prices, calendar, earnings history) are refreshed only when stale; use
`make refresh-all` to force.

## Layout

| Path | What it does |
|---|---|
| `ingest/prices.py` | 15 yr daily OHLCV for current S&P 500 (Wikipedia constituents) → `data/prices.parquet` |
| `ingest/calendar.py` | Next-21-day earnings calendar: yfinance × Nasdaq (optional Finnhub) cross-check; conflicting names dropped; BMO/AMC flagged |
| `ingest/earnings_history.py` | Historical earnings dates per upcoming reporter + Alpha Vantage backfill queue (25 calls/day, 5/min, key from `ALPHAVANTAGE_API_KEY`) |
| `features/moves.py` | Realized earnings-day moves with BMO/AMC alignment |
| `model/fair_move.py` | Empirical-Bayes fair-move estimate (w = n/(n+6)) + scaled-t tails; `uv run python -m model.fair_move --sanity` for the calibration harness |
| `ingest/chains.py` | ATM straddle implied move (mid/bid/ask, spread %, OI) for names reporting in the next 10 trading days |
| `scoring/rank.py` | Edge score, liquidity screen (spread > 10% or OI < 500 ⇒ drop), strategy mapping with max loss ≤ $250 |
| `dashboard/daily.py` | Ranked HTML + CSV |
| `log/predictions.py` | Pre-registration writer → `log/predictions.csv` (the experiment) |
| `run.py` | Single entrypoint (`make daily`) |

`data/` is gitignored (caches + generated dashboards); `log/predictions.csv`
is committed — it is the experiment record.

## Publishing

**GitHub Pages (default):** `scripts/publish_pages.sh` pushes the latest
dashboard (stable `index.html`, dated HTML/CSV, `predictions.csv`) to the
`gh-pages` branch — live at
<https://pykerl.github.io/earnings_trade_engine/>. `scripts/cron_daily.sh`
does this automatically after each run (disable with `ETE_PUBLISH_PAGES=0`).

**FTPS (optional alternative):** when these env vars are set, `make daily`
ends by uploading the same files over FTPS:

```
ETE_UPLOAD_HOST=ftp.example.com
ETE_UPLOAD_USER=...
ETE_UPLOAD_PASSWORD=...
ETE_UPLOAD_DIR=public_html/earnings
ETE_UPLOAD_PROTOCOL=ftps   # default; "ftp" allowed but discouraged (cleartext)
ETE_UPLOAD_PORT=21         # default
```

Credentials come from the environment only. Note: FTP needs outbound port
21 — that works from a normal machine/cron box, but NOT from Claude Code
cloud sandboxes, whose egress is HTTPS(443)-only.

### Local daily cron (the intended production setup)

```bash
git clone https://github.com/pykerl/earnings_trade_engine.git
cd earnings_trade_engine
curl -LsSf https://astral.sh/uv/install.sh | sh   # if uv isn't installed
make setup
cp .env.example .env && $EDITOR .env               # fill in keys + FTP creds
./scripts/cron_daily.sh                            # test one run by hand
crontab -e                                         # then schedule it:
#   CRON_TZ=America/New_York
#   30 16 * * 1-5  /ABSOLUTE/PATH/earnings_trade_engine/scripts/cron_daily.sh
```

Each weekday at 4:30pm ET the script refreshes chains against the day's
close, rescores, uploads the dashboard to your site (stable URL: the
`index.html` in `ETE_UPLOAD_DIR`), appends new pre-registration rows, and
pushes `log/predictions.csv` so the experiment record stays in git
(disable with `ETE_GIT_PUSH_LOG=0`). Run logs land in `data/logs/`.

## Offline / fixtures

Every module has a network-free smoke test (`make test`). For plumbing
verification without network access, `uv run python run.py daily --fixtures`
runs the identical pipeline on clearly-labeled synthetic data; outputs are
watermarked and pre-registration rows go to `data/demo/predictions_demo.csv`,
never to the real log.
