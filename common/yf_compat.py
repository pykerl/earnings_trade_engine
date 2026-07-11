"""Pin yfinance's TLS fingerprint to one that survives TLS-inspecting proxies.

yfinance >= 1.x sends requests through curl_cffi impersonating current Chrome.
Modern Chrome's ClientHello (post-quantum X25519MLKEM768 key share) gets the
connection reset by some TLS-terminating egress proxies — including the one in
Claude Code cloud sandboxes — surfacing as
    curl: (35) Recv failure: Connection reset by peer
on every Yahoo call. Older browser fingerprints negotiate fine, and Yahoo
accepts them (plain requests without impersonation gets 429'd instead).

yfinance's `new_session()` hardcodes impersonate="chrome" and is imported
by-name across its modules, so we swap the `_backend` object that the factory
resolves at call time for a shim whose Session() pins the profile.

Override with ETE_YF_IMPERSONATE (any curl_cffi profile name, or "off" to
keep upstream behavior).
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("ete.yf_compat")

DEFAULT_IMPERSONATE = "chrome110"

_patched = False


def patch_yfinance_tls() -> None:
    """Idempotent; safe to call before any yfinance network use."""
    global _patched
    if _patched:
        return
    profile = os.environ.get("ETE_YF_IMPERSONATE", DEFAULT_IMPERSONATE)
    if profile.lower() in ("", "off", "none", "default"):
        _patched = True
        return

    import yfinance._http as yhttp

    if not getattr(yhttp, "HAS_CURL_CFFI", False):
        _patched = True  # requests fallback backend: nothing to pin
        return

    real_backend = yhttp._backend

    class _BackendShim:
        """Delegates to curl_cffi.requests but pins Session impersonation."""

        def __getattr__(self, name):
            return getattr(real_backend, name)

        @staticmethod
        def Session(*args, **kwargs):
            kwargs["impersonate"] = profile
            return real_backend.Session(*args, **kwargs)

    yhttp._backend = _BackendShim()
    _patched = True
    log.info("yfinance TLS impersonation pinned to %r (proxy compatibility)", profile)
