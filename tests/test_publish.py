import ftplib

import pytest

from dashboard import publish


class FakeFTP:
    instances = []

    def __init__(self):
        self.stored = []
        self.cwds = []
        self.mkds = []
        self.protected = False
        self.quit_called = False
        FakeFTP.instances.append(self)

    def connect(self, host, port, timeout=None):
        self.host, self.port = host, port

    def login(self, user, password):
        self.user, self.password = user, password

    def prot_p(self):
        self.protected = True

    def cwd(self, d):
        if d not in self.mkds and d.startswith("new_"):
            raise ftplib.error_perm("550")
        self.cwds.append(d)

    def mkd(self, d):
        self.mkds.append(d)

    def storbinary(self, cmd, fh):
        self.stored.append(cmd)

    def quit(self):
        self.quit_called = True


@pytest.fixture
def creds(monkeypatch):
    monkeypatch.setenv("ETE_UPLOAD_HOST", "ftp.example.com")
    monkeypatch.setenv("ETE_UPLOAD_USER", "u")
    monkeypatch.setenv("ETE_UPLOAD_PASSWORD", "p")
    monkeypatch.setenv("ETE_UPLOAD_DIR", "public_html/earnings")
    monkeypatch.delenv("ETE_UPLOAD_PROTOCOL", raising=False)


def test_not_configured_skips(monkeypatch, tmp_path):
    for var in ("ETE_UPLOAD_HOST", "ETE_UPLOAD_USER", "ETE_UPLOAD_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    assert publish.configured() is False
    assert publish.publish([(tmp_path / "x.html", "x.html")]) is False


def test_publish_dashboard_uploads_stable_index(monkeypatch, tmp_path, creds):
    FakeFTP.instances.clear()
    monkeypatch.setattr(ftplib, "FTP_TLS", FakeFTP)
    html = tmp_path / "daily_2026-07-11.html"
    csv = tmp_path / "daily_2026-07-11.csv"
    preds = tmp_path / "predictions.csv"
    for f in (html, csv, preds):
        f.write_text("x")

    assert publish.publish_dashboard(html, csv, preds) is True
    ftp = FakeFTP.instances[-1]
    assert ftp.protected, "FTPS must protect the data channel"
    assert ftp.quit_called
    assert ftp.cwds[:2] == ["public_html", "earnings"]
    assert ftp.stored == [
        "STOR daily_2026-07-11.html",
        "STOR index.html",
        "STOR daily_2026-07-11.csv",
        "STOR predictions.csv",
    ]


def test_publish_retries_then_fails(monkeypatch, tmp_path, creds):
    class BoomFTP(FakeFTP):
        def connect(self, *a, **k):
            raise OSError("port blocked")

    monkeypatch.setattr(ftplib, "FTP_TLS", BoomFTP)
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    f = tmp_path / "a.html"
    f.write_text("x")
    assert publish.publish([(f, "a.html")]) is False


def test_rejects_unknown_protocol(monkeypatch, tmp_path, creds):
    monkeypatch.setenv("ETE_UPLOAD_PROTOCOL", "gopher")
    monkeypatch.setattr(publish.time, "sleep", lambda s: None)
    f = tmp_path / "a.html"
    f.write_text("x")
    assert publish.publish([(f, "a.html")]) is False
