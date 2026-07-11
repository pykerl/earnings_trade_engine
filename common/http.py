"""Shared requests session with browser-ish UA and bounded retries."""

from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger("ete.http")

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json, text/html;q=0.9,*/*;q=0.8"})
    return s


def get_with_retries(
    session: requests.Session,
    url: str,
    *,
    params: dict | None = None,
    retries: int = 3,
    backoff: float = 2.0,
    timeout: float = 30.0,
) -> requests.Response | None:
    """GET with exponential backoff. Returns None (and logs) on final failure."""
    for attempt in range(retries):
        try:
            resp = session.get(url, params=params, timeout=timeout)
            if resp.status_code == 200:
                return resp
            log.warning("GET %s -> HTTP %s (attempt %d/%d)", url, resp.status_code, attempt + 1, retries)
        except requests.RequestException as exc:
            log.warning("GET %s failed: %s (attempt %d/%d)", url, exc, attempt + 1, retries)
        if attempt < retries - 1:
            time.sleep(backoff * (2**attempt))
    log.error("GET %s: giving up after %d attempts", url, retries)
    return None
