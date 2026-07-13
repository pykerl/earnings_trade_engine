"""Reddit ticker-mention flow (plan_reddit_growth §1, step 4).

Primary: ApeWisdom free API — pre-aggregated daily mentions/upvotes per
ticker for r/wallstreetbets (no key). Each run stores a dated snapshot under
data/mentions/; the trailing 30d-vs-180d mention-velocity z-score is
computed from OUR accumulated snapshots because ApeWisdom exposes no
history. Until >= MIN_HISTORY_DAYS of snapshots exist, the crowding proxy
degrades to (mentions vs 24h ago + rank) and is flagged
`velocity_mode="short-history"` — never silently pretended to be a z-score.

Fallback: a PRAW sampler for the WSB daily thread, used ONLY when
REDDIT_CLIENT_ID/SECRET/USER_AGENT are set (official OAuth per Reddit ToS —
no scraping around the API). Without credentials it logs and returns empty:
cohort-only mode.

Output: data/mentions_latest.parquet (+ dated snapshots)
"""

from __future__ import annotations

import logging
import os
import re
from collections import Counter
from datetime import date

import numpy as np
import pandas as pd

from common import config
from common.http import get_with_retries, make_session

log = logging.getLogger("ete.mentions")

APEWISDOM_URL = "https://apewisdom.io/api/v1.0/filter/{flt}/page/{page}"
MENTIONS_DIR = config.DATA_DIR / "mentions"
MENTIONS_LATEST = config.DATA_DIR / "mentions_latest.parquet"
MIN_HISTORY_DAYS = 30
MAX_PAGES = 5

REDDIT_ENV = ("REDDIT_CLIENT_ID", "REDDIT_CLIENT_SECRET", "REDDIT_USER_AGENT")

TICKER_RE = re.compile(r"\$([A-Z]{1,5})\b|\b([A-Z]{2,5})\b")


# ------------------------------------------------------------- ApeWisdom ----
def fetch_apewisdom(flt: str = "wallstreetbets", session=None) -> pd.DataFrame:
    """All pages of today's snapshot; empty frame on total failure."""
    session = session or make_session()
    rows, page, pages = [], 1, 1
    while page <= min(pages, MAX_PAGES):
        resp = get_with_retries(session, APEWISDOM_URL.format(flt=flt, page=page), retries=2)
        if resp is None:
            break
        try:
            payload = resp.json()
            pages = int(payload.get("pages", 1))
            for r in payload.get("results", []):
                rows.append(
                    {
                        "ticker": str(r.get("ticker", "")).upper(),
                        "mentions": int(r.get("mentions") or 0),
                        "upvotes": int(r.get("upvotes") or 0),
                        "rank": int(r.get("rank") or 0),
                        "mentions_24h_ago": int(r.get("mentions_24h_ago") or 0),
                    }
                )
        except (ValueError, TypeError) as exc:
            log.warning("apewisdom parse failed on page %d: %s", page, exc)
            break
        page += 1
    df = pd.DataFrame(rows).drop_duplicates("ticker")
    if df.empty:
        log.warning("ApeWisdom unavailable — degrading to cohort-only mode")
    else:
        log.info("apewisdom: %d tickers", len(df))
    return df


def store_snapshot(df: pd.DataFrame, day: date) -> None:
    if df.empty:
        return
    MENTIONS_DIR.mkdir(parents=True, exist_ok=True)
    df.assign(date=day.isoformat()).to_parquet(MENTIONS_DIR / f"{day}.parquet", index=False)


def load_history() -> pd.DataFrame:
    files = sorted(MENTIONS_DIR.glob("*.parquet"))
    if not files:
        return pd.DataFrame(columns=["ticker", "mentions", "date"])
    return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


def mention_velocity(history: pd.DataFrame, today_df: pd.DataFrame) -> pd.DataFrame:
    """30d-vs-180d z-score when history allows; honest fallback otherwise."""
    out = today_df.copy()
    days = history["date"].nunique() if len(history) else 0
    if days >= MIN_HISTORY_DAYS:
        out["velocity_mode"] = "zscore"
        stats = []
        hist = history.copy()
        hist["date"] = pd.to_datetime(hist["date"])
        cutoff30 = hist["date"].max() - pd.Timedelta(days=30)
        cutoff180 = hist["date"].max() - pd.Timedelta(days=180)
        base = hist[hist["date"] >= cutoff180]
        for t, g in base.groupby("ticker"):
            recent = g[g["date"] >= cutoff30]["mentions"]
            older = g[g["date"] < cutoff30]["mentions"]  # baseline EXCLUDES the recent window
            if len(older) < 5 or not len(recent):
                stats.append({"ticker": t, "velocity_z": 0.0})
                continue
            mu, sd = older.mean(), older.std(ddof=1)
            stats.append(
                {"ticker": t,
                 "velocity_z": float((recent.mean() - mu) / sd) if sd and sd > 0 else 0.0}
            )
        out = out.merge(pd.DataFrame(stats), on="ticker", how="left")
    else:
        out["velocity_mode"] = "short-history"
        # 24h ratio as a weak stand-in, squashed to a z-like range
        ratio = (out["mentions"] + 1) / (out["mentions_24h_ago"] + 1)
        out["velocity_z"] = np.clip(np.log2(ratio), -3, 3)
        log.info(
            "mention history has %d day(s); z-score needs %d — using 24h-ratio proxy "
            "(flagged short-history)", days, MIN_HISTORY_DAYS,
        )
    return out


# ------------------------------------------------------- PRAW fallback ------
def reddit_credentials_present() -> bool:
    return all(os.environ.get(v) for v in REDDIT_ENV)


def fetch_praw_daily_thread(limit_comments: int = 500) -> pd.DataFrame:
    """Official-API sampler of the WSB daily thread; inert without creds."""
    cols = ["ticker", "mentions"]
    if not reddit_credentials_present():
        log.info("REDDIT_* credentials not set — PRAW fallback inactive (cohort-only mode)")
        return pd.DataFrame(columns=cols)
    try:
        import praw  # optional dependency, only needed with credentials
    except ImportError:
        log.warning("praw not installed; run `uv add praw` to enable the Reddit fallback")
        return pd.DataFrame(columns=cols)
    reddit = praw.Reddit(
        client_id=os.environ["REDDIT_CLIENT_ID"],
        client_secret=os.environ["REDDIT_CLIENT_SECRET"],
        user_agent=os.environ["REDDIT_USER_AGENT"],
    )
    counter: Counter = Counter()
    sub = reddit.subreddit("wallstreetbets")
    for post in sub.hot(limit=5):
        if "daily" not in post.title.lower():
            continue
        post.comments.replace_more(limit=0)
        for c in post.comments.list()[:limit_comments]:
            for m in TICKER_RE.finditer(getattr(c, "body", "") or ""):
                tick = (m.group(1) or m.group(2) or "").upper()
                if 1 < len(tick) <= 5:
                    counter[tick] += 1
    return pd.DataFrame(
        [{"ticker": t, "mentions": n} for t, n in counter.most_common(200)], columns=cols
    )


# --------------------------------------------------------------------- run --
def run(today: date | None = None) -> pd.DataFrame:
    config.ensure_dirs()
    today = today or date.today()
    df = fetch_apewisdom()
    if df.empty and reddit_credentials_present():
        df = fetch_praw_daily_thread()
        df["upvotes"] = 0
        df["rank"] = range(1, len(df) + 1)
        df["mentions_24h_ago"] = 0
    if df.empty:
        log.warning("no mention data from any source — cohort-only mode")
        out = pd.DataFrame(
            columns=["ticker", "mentions", "upvotes", "rank", "mentions_24h_ago",
                     "velocity_mode", "velocity_z"]
        )
        out.to_parquet(MENTIONS_LATEST, index=False)
        return out
    store_snapshot(df, today)
    out = mention_velocity(load_history(), df)
    out.to_parquet(MENTIONS_LATEST, index=False)
    log.info("mentions -> %s (%d tickers, mode=%s)", MENTIONS_LATEST, len(out),
             out["velocity_mode"].iloc[0] if len(out) else "n/a")
    return out


if __name__ == "__main__":
    config.setup_logging()
    run()
