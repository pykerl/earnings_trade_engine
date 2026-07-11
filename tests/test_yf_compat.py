import importlib

from common import yf_compat


def test_patch_pins_impersonation(monkeypatch):
    monkeypatch.delenv("ETE_YF_IMPERSONATE", raising=False)
    importlib.reload(yf_compat)

    import yfinance._http as yhttp

    if not getattr(yhttp, "HAS_CURL_CFFI", False):
        return  # requests fallback backend: patch is a no-op by design

    captured = {}
    real_backend = yhttp._backend

    class FakeBackend:
        def __getattr__(self, name):
            return getattr(real_backend, name)

        @staticmethod
        def Session(*args, **kwargs):
            captured.update(kwargs)
            return object()

    monkeypatch.setattr(yhttp, "_backend", FakeBackend())
    yf_compat.patch_yfinance_tls()
    yhttp.new_session()
    assert captured.get("impersonate") == yf_compat.DEFAULT_IMPERSONATE

    # idempotent: second call must not re-wrap the shim
    shim = yhttp._backend
    yf_compat.patch_yfinance_tls()
    assert yhttp._backend is shim


def test_patch_can_be_disabled(monkeypatch):
    monkeypatch.setenv("ETE_YF_IMPERSONATE", "off")
    importlib.reload(yf_compat)

    import yfinance._http as yhttp

    before = yhttp._backend
    yf_compat.patch_yfinance_tls()
    assert yhttp._backend is before
