"""core.tls_trust: the CA source chosen per platform, and the real effect on urllib.

Regression for 2.0.0 on macOS: the frozen app's OpenSSL looked for the build machine's CA file, so
every urllib request on a user's Mac failed with CERTIFICATE_VERIFY_FAILED.
"""

from __future__ import annotations

import http.server
import json
import os
import ssl
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from core import tls_trust
from core.server.tls import generate_self_signed_cert

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_env(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    monkeypatch.setattr(tls_trust, "source", "not configured")


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A stand-in for certifi's cacert.pem."""
    pem = tmp_path / "cacert.pem"
    pem.write_text("-----BEGIN CERTIFICATE-----\nstand-in\n-----END CERTIFICATE-----\n", encoding="ascii")
    monkeypatch.setattr(tls_trust, "_certifi_file", lambda: str(pem))
    return str(pem)


def _platform(monkeypatch, name: str, frozen: bool, default_has_certs: bool) -> None:
    monkeypatch.setattr(tls_trust.sys, "platform", name)
    if frozen:
        monkeypatch.setattr(tls_trust.sys, "frozen", True, raising=False)
    else:
        monkeypatch.delattr(tls_trust.sys, "frozen", raising=False)
    monkeypatch.setattr(tls_trust, "_default_store_has_certs", lambda: default_has_certs)


def test_frozen_macos_uses_the_bundled_certifi_even_when_a_default_store_exists(clean_env, bundle, monkeypatch):
    _platform(monkeypatch, "darwin", frozen=True, default_has_certs=True)
    assert tls_trust.configure() == "certifi"
    assert os.environ["SSL_CERT_FILE"] == bundle


def test_macos_from_source_without_a_default_store_falls_back_to_certifi(clean_env, bundle, monkeypatch):
    _platform(monkeypatch, "darwin", frozen=False, default_has_certs=False)
    assert tls_trust.configure() == "certifi"
    assert os.environ["SSL_CERT_FILE"] == bundle


@pytest.mark.parametrize("name", ["darwin", "linux"])
def test_a_usable_default_store_is_kept_when_not_frozen(clean_env, bundle, monkeypatch, name):
    _platform(monkeypatch, name, frozen=False, default_has_certs=True)
    assert tls_trust.configure() == "system"
    assert "SSL_CERT_FILE" not in os.environ


@pytest.mark.parametrize("frozen", [False, True])
def test_windows_is_left_to_the_system_store(clean_env, bundle, monkeypatch, frozen):
    _platform(monkeypatch, "win32", frozen=frozen, default_has_certs=False)
    assert tls_trust.configure() == "system"
    assert "SSL_CERT_FILE" not in os.environ


@pytest.mark.parametrize("var", ["SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_a_variable_the_user_set_is_never_overridden(clean_env, bundle, monkeypatch, var):
    _platform(monkeypatch, "darwin", frozen=True, default_has_certs=False)
    monkeypatch.setenv(var, "/users/own/ca.pem")
    assert tls_trust.configure() == "env"
    assert os.environ[var] == "/users/own/ca.pem"
    if var == "SSL_CERT_DIR":
        assert "SSL_CERT_FILE" not in os.environ


def test_no_certifi_and_no_store_reports_none_and_sets_nothing(clean_env, monkeypatch):
    _platform(monkeypatch, "linux", frozen=False, default_has_certs=False)
    monkeypatch.setattr(tls_trust, "_certifi_file", lambda: None)
    assert tls_trust.configure() == "none"
    assert "SSL_CERT_FILE" not in os.environ


def test_certifi_file_is_the_real_bundle_when_certifi_is_installed():
    certifi = pytest.importorskip("certifi")
    assert tls_trust._certifi_file() == certifi.where()


def test_default_store_check_reads_the_compiled_in_paths(tmp_path, monkeypatch):
    empty_dir = tmp_path / "certs"
    empty_dir.mkdir()
    paths = ssl.DefaultVerifyPaths(None, None, "SSL_CERT_FILE",  # type: ignore[arg-type]  # None as at runtime
                                   str(tmp_path / "missing.pem"), "SSL_CERT_DIR", str(empty_dir))
    monkeypatch.setattr(tls_trust.ssl, "get_default_verify_paths", lambda: paths)
    assert tls_trust._default_store_has_certs() is False
    (empty_dir / "abcd1234.0").write_text("x", encoding="ascii")
    assert tls_trust._default_store_has_certs() is True


# --- the real effect: a local HTTPS server whose certificate only the "bundle" trusts --------------

class _Hello(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802 - stdlib handler name
        body = b"hello"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


@pytest.fixture
def https_server(tmp_path):
    cert, key = tmp_path / "server.pem", tmp_path / "server.key"
    generate_self_signed_cert(cert, key, hosts=["localhost", "127.0.0.1"])
    httpd = http.server.HTTPServer(("127.0.0.1", 0), _Hello)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"https://127.0.0.1:{httpd.server_address[1]}/", str(cert)
    finally:
        httpd.shutdown()
        httpd.server_close()


def _relaxed_default_context(monkeypatch):
    """The test certificate is its own trust anchor without CA flags; Python 3.13+'s strict default
    would reject that for reasons unrelated to WHERE the trust store comes from, which is what is
    tested here. The context still loads its CAs from the default paths, like urllib's."""
    real = ssl.create_default_context

    def make(*args, **kwargs):
        ctx = real(*args, **kwargs)
        ctx.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        return ctx

    monkeypatch.setattr(ssl, "_create_default_https_context", make)


def test_urllib_fails_without_the_bundle_and_works_after_configure(clean_env, https_server, monkeypatch):
    url, server_cert = https_server
    _relaxed_default_context(monkeypatch)
    # urlopen's shared opener keeps the SSL context it made first (Python 3.13+ builds it in
    # HTTPSHandler.__init__), which is why configure() runs before any request in gui.main().
    monkeypatch.setattr(urllib.request, "_opener", None)
    # The user's Mac in 2.0.0: frozen, and the compiled-in CA file is the build machine's.
    _platform(monkeypatch, "darwin", frozen=True, default_has_certs=False)
    with pytest.raises(urllib.error.URLError) as before:
        urllib.request.urlopen(url, timeout=10)
    assert isinstance(before.value.reason, ssl.SSLCertVerificationError)

    monkeypatch.setattr(tls_trust, "_certifi_file", lambda: server_cert)
    assert tls_trust.configure() == "certifi"
    monkeypatch.setattr(urllib.request, "_opener", None)
    with urllib.request.urlopen(url, timeout=10) as resp:
        assert resp.read() == b"hello"


def test_self_check_flag_prints_the_choice_and_exits(clean_env):
    env = {k: v for k, v in os.environ.items() if k not in ("SSL_CERT_FILE", "SSL_CERT_DIR")}
    out = subprocess.run([sys.executable, str(REPO / "gui.py"), "--tls-self-check"], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=120, check=True).stdout
    info = json.loads(out.strip().splitlines()[-1])
    assert info["source"] in {"system", "certifi", "none"}
    assert set(info) >= {"cafile", "capath", "openssl_cafile", "openssl"}


def test_a_child_process_inherits_the_choice(clean_env, bundle, monkeypatch):
    _platform(monkeypatch, "darwin", frozen=True, default_has_certs=False)
    tls_trust.configure()
    out = subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('SSL_CERT_FILE'))"],
                         capture_output=True, text=True, timeout=60, check=True).stdout.strip()
    assert out == bundle
