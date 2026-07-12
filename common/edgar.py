"""Shared EDGAR HTTP plumbing: SEC-compliant User-Agent + rate limiting.

SEC fair-access rules: declare who you are in the User-Agent and stay under
10 requests/second. Every EDGAR call in this repo goes through this module.
"""

from __future__ import annotations

import logging
import threading
import time

import requests

from common import config

log = logging.getLogger("ete.edgar")


class RateLimiter:
    """Simple thread-safe min-interval limiter (config.EDGAR_MAX_RPS)."""

    def __init__(self, max_rps: float = config.EDGAR_MAX_RPS, clock=None, sleeper=None):
        self.min_interval = 1.0 / max_rps
        self.clock = clock or time.monotonic
        self.sleeper = sleeper or time.sleep
        self._lock = threading.Lock()
        self._next_ok = 0.0

    def acquire(self) -> None:
        with self._lock:
            now = self.clock()
            wait = self._next_ok - now
            self._next_ok = max(now, self._next_ok) + self.min_interval
        if wait > 0:
            self.sleeper(wait)


_limiter = RateLimiter()


def make_edgar_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "User-Agent": config.EDGAR_USER_AGENT,
            "Accept-Encoding": "gzip, deflate",
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
        }
    )
    return s


def edgar_get(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    retries: int = 3,
    timeout: float = 60.0,
    stream: bool = False,
    limiter: RateLimiter | None = None,
):
    """Rate-limited GET with backoff; None on final failure (logged)."""
    limiter = limiter or _limiter
    for attempt in range(retries):
        limiter.acquire()
        try:
            resp = session.get(url, params=params, timeout=timeout, stream=stream)
            if resp.status_code == 200:
                return resp
            if resp.status_code == 429:
                log.warning("EDGAR 429 (slow down) on %s; backing off", url)
                time.sleep(5 * (attempt + 1))
                continue
            log.warning("EDGAR GET %s -> HTTP %s (attempt %d)", url, resp.status_code, attempt + 1)
        except requests.RequestException as exc:
            log.warning("EDGAR GET %s failed: %s (attempt %d)", url, exc, attempt + 1)
        if attempt < retries - 1:
            time.sleep(2 * (attempt + 1))
    log.error("EDGAR GET %s: giving up after %d attempts", url, retries)
    return None
