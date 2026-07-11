"""Pre-registration log — the experiment itself (plan §3 block 4).

Every upcoming event gets ONE frozen row in log/predictions.csv written
strictly BEFORE it reports: fair move, implied move, chosen structure, and
the hypothetical entry at realistic prices (long structures priced at the
ask, short structures at the bid — that is already the `entry_price`
convention set in scoring). Screened and no-trade events are registered too;
season-end calibration (plan §4) needs the full distribution, not just the
trades.

Append-only by construction:
  * a (ticker, earnings_date) key that already exists is never touched,
  * rows are appended with csv append mode — past rows are never rewritten,
  * only events strictly after the run date are eligible (an event that
    reports today may already be public by the time an EOD run happens).
"""

from __future__ import annotations

import csv
import logging
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from common import config

log = logging.getLogger("ete.predictions")

FIELDS = [
    "registered_at", "ticker", "earnings_date", "session", "expiry",
    "spot", "atm_strike",
    "fair_move", "ci_low", "ci_high",
    "implied_move_bid", "implied_move_mid", "implied_move_ask",
    "straddle_bid", "straddle_mid", "straddle_ask",
    "edge", "z", "score", "structure", "detail", "entry_side", "entry_price",
    "max_gain", "max_loss", "spread_pct", "open_interest",
    "n_events", "conf_mult", "screened", "screen_reason", "flags",
]


def existing_keys(path: Path) -> set[tuple[str, str]]:
    if not path.exists():
        return set()
    try:
        prior = pd.read_csv(path, usecols=["ticker", "earnings_date"], dtype=str)
    except (ValueError, OSError) as exc:
        raise RuntimeError(
            f"could not read {path} — refusing to append blindly to the experiment log: {exc}"
        )
    return set(zip(prior["ticker"], prior["earnings_date"]))


def _clean(value):
    if isinstance(value, float):
        if np.isinf(value):
            return "inf"
        if np.isnan(value):
            return ""
    return value


def register(
    scored: pd.DataFrame,
    today: date | None = None,
    path: Path | None = None,
) -> pd.DataFrame:
    """Append frozen rows for not-yet-reported, not-yet-registered events."""
    today = today or date.today()
    path = path or config.PREDICTIONS_CSV
    path.parent.mkdir(parents=True, exist_ok=True)

    seen = existing_keys(path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    new_rows = []
    for r in scored.itertuples(index=False):
        ev_date = r.earnings_date if isinstance(r.earnings_date, date) else pd.Timestamp(r.earnings_date).date()
        if ev_date <= today:
            continue  # never register an event that may already be public
        key = (str(r.ticker), ev_date.isoformat())
        if key in seen:
            continue  # frozen: first registration wins, forever
        row = {f: _clean(getattr(r, f, "")) for f in FIELDS}
        row["registered_at"] = now
        row["earnings_date"] = ev_date.isoformat()
        new_rows.append(row)
        seen.add(key)

    if new_rows:
        write_header = not path.exists()
        with path.open("a", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=FIELDS)
            if write_header:
                writer.writeheader()
            writer.writerows(new_rows)
    log.info("pre-registered %d new events -> %s", len(new_rows), path)
    return pd.DataFrame(new_rows, columns=FIELDS)


if __name__ == "__main__":
    config.setup_logging()
    register(pd.read_parquet(config.SCORED_PARQUET))
