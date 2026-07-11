"""Publish the daily dashboard to a web host over FTP/FTPS (opt-in).

Runs automatically at the end of `make daily` when credentials are present
in the environment — never hardcoded, never committed:

    ETE_UPLOAD_HOST       e.g. ftp.paulkerl.com          (required)
    ETE_UPLOAD_USER                                       (required)
    ETE_UPLOAD_PASSWORD                                   (required)
    ETE_UPLOAD_DIR        e.g. public_html/earnings       (default: "")
    ETE_UPLOAD_PROTOCOL   ftps (default) | ftp
    ETE_UPLOAD_PORT       default 21

Uploads the dated HTML/CSV, a copy of the HTML as index.html (stable URL),
and the pre-registration log. Plain FTP sends the password in cleartext;
prefer FTPS (explicit TLS) — the default — unless the host truly can't.

Fixture/demo output is never published (run.py only calls this on live runs).
"""

from __future__ import annotations

import ftplib
import logging
import os
import time
from pathlib import Path

log = logging.getLogger("ete.publish")

RETRIES = 3


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def configured() -> bool:
    return bool(_env("ETE_UPLOAD_HOST") and _env("ETE_UPLOAD_USER") and _env("ETE_UPLOAD_PASSWORD"))


def _connect() -> ftplib.FTP:
    protocol = _env("ETE_UPLOAD_PROTOCOL", "ftps").lower()
    host = _env("ETE_UPLOAD_HOST")
    port = int(_env("ETE_UPLOAD_PORT", "21"))
    if protocol == "ftps":
        ftp: ftplib.FTP = ftplib.FTP_TLS()
    elif protocol == "ftp":
        log.warning("plain FTP sends credentials in cleartext; use ftps if the host supports it")
        ftp = ftplib.FTP()
    else:
        raise ValueError(f"unsupported ETE_UPLOAD_PROTOCOL={protocol!r} (use ftps or ftp)")
    ftp.connect(host, port, timeout=30)
    ftp.login(_env("ETE_UPLOAD_USER"), _env("ETE_UPLOAD_PASSWORD"))
    if isinstance(ftp, ftplib.FTP_TLS):
        ftp.prot_p()  # encrypt the data channel too
    return ftp


def _chdir_make(ftp: ftplib.FTP, remote_dir: str) -> None:
    for part in [p for p in remote_dir.split("/") if p]:
        try:
            ftp.cwd(part)
        except ftplib.error_perm:
            ftp.mkd(part)
            ftp.cwd(part)


def publish(files: list[tuple[Path, str]]) -> bool:
    """Upload (local_path, remote_name) pairs; True on full success."""
    if not configured():
        log.info("upload env vars not set; skipping publish")
        return False
    remote_dir = _env("ETE_UPLOAD_DIR")
    last_exc: Exception | None = None
    for attempt in range(RETRIES):
        try:
            ftp = _connect()
            try:
                if remote_dir:
                    _chdir_make(ftp, remote_dir)
                for local, remote_name in files:
                    with local.open("rb") as fh:
                        ftp.storbinary(f"STOR {remote_name}", fh)
                    log.info("uploaded %s -> %s/%s", local.name, remote_dir or ".", remote_name)
            finally:
                ftp.quit()
            return True
        except Exception as exc:
            last_exc = exc
            log.warning("publish attempt %d/%d failed: %s", attempt + 1, RETRIES, exc)
            if attempt < RETRIES - 1:
                time.sleep(2 * (attempt + 1))
    log.error("publish failed after %d attempts: %s", RETRIES, last_exc)
    return False


def publish_dashboard(html_path: Path, csv_path: Path, predictions_path: Path | None = None) -> bool:
    files = [
        (html_path, html_path.name),
        (html_path, "index.html"),  # stable URL for viewing on the fly
        (csv_path, csv_path.name),
    ]
    if predictions_path is not None and predictions_path.exists():
        files.append((predictions_path, "predictions.csv"))
    return publish(files)
