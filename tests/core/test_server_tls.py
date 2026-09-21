"""HTTPS: self-signed certificate generation/reuse + a real TLS round-trip.

Hermetic: the certificate is written under ``tmp_path`` (the real user-data
directory is never touched — ``tls.cert_dir`` is monkeypatched for the
ServerHandle test), and the only socket is an ephemeral loopback bind.
"""
from __future__ import annotations

import json
import os
import ssl
import urllib.request

from core.server import ServerHandle, reachable_urls
from core.server import tls


def _writing_transcribe(task, progress_cb=None, log_cb=None, language_cb=None):
    base, _ = os.path.splitext(task.file_path)
    with open(f"{base}.srt", "w", encoding="utf-8") as f:
        f.write("dummy srt")
    task.output_paths = [f"{base}.srt"]
    if progress_cb:
        progress_cb(100)


def test_reachable_urls_uses_https_scheme():
    assert reachable_urls("127.0.0.1", 8765, https=True) == [
        "https://127.0.0.1:8765/"]
    assert reachable_urls("127.0.0.1", 8765) == ["http://127.0.0.1:8765/"]


def test_generate_self_signed_certificate_loads(tmp_path):
    cert = tmp_path / "server_cert.pem"
    key = tmp_path / "server_key.pem"
    tls.generate_self_signed_cert(cert, key, hosts=["localhost", "127.0.0.1"])
    assert cert.is_file() and key.is_file()
    assert "BEGIN CERTIFICATE" in cert.read_text(encoding="ascii")
    assert "BEGIN PRIVATE KEY" in key.read_text(encoding="ascii")
    # OpenSSL itself must accept the pair.
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))


def test_generate_rejects_non_ascii_host_without_crashing(tmp_path):
    cert = tmp_path / "c.pem"
    key = tmp_path / "k.pem"
    # A non-IDNA-encodable host is skipped, not fatal.
    tls.generate_self_signed_cert(
        cert, key, hosts=["localhost", "\u2603.example"])
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=str(cert), keyfile=str(key))


def test_ensure_certificate_reuses_existing_pair(tmp_path):
    cert = tmp_path / "server_cert.pem"
    key = tmp_path / "server_key.pem"
    tls.generate_self_signed_cert(cert, key)
    before = cert.read_bytes(), key.read_bytes()
    got_cert, got_key = tls.ensure_certificate(cert, key)
    assert (got_cert, got_key) == (str(cert), str(key))
    assert (cert.read_bytes(), key.read_bytes()) == before


def test_ensure_certificate_regenerates_invalid_pair(tmp_path):
    cert = tmp_path / "server_cert.pem"
    key = tmp_path / "server_key.pem"
    cert.write_text("not a certificate", encoding="ascii")
    key.write_text("not a key", encoding="ascii")
    got_cert, got_key = tls.ensure_certificate(cert, key)
    assert (got_cert, got_key) == (str(cert), str(key))
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(certfile=got_cert, keyfile=got_key)


def test_build_server_ssl_context(tmp_path):
    ctx = tls.build_server_ssl_context(
        tmp_path / "server_cert.pem", tmp_path / "server_key.pem")
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2


def test_https_round_trip_over_real_socket(tmp_path, monkeypatch):
    monkeypatch.setattr(tls, "cert_dir", lambda: tmp_path)
    handle = ServerHandle(
        transcribe_fn=_writing_transcribe, load_model=False)
    handle.start("127.0.0.1", 0, https=True)
    try:
        assert handle.is_running()
        urls = handle.urls()
        assert urls and urls[0].startswith("https://127.0.0.1:")
        client_ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(
            urls[0] + "api/health", context=client_ctx, timeout=5,
        ) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        assert body["status"] == "ok"
    finally:
        handle.stop()
    assert not handle.is_running()


def test_https_failure_does_not_leave_server_running(tmp_path, monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("no cert for you")

    monkeypatch.setattr(tls, "build_server_ssl_context", _boom)
    handle = ServerHandle(
        transcribe_fn=_writing_transcribe, load_model=False)
    raised = False
    try:
        handle.start("127.0.0.1", 0, https=True)
    except RuntimeError:
        raised = True
    assert raised, "an HTTPS start without a certificate must fail loudly"
    assert not handle.is_running()
