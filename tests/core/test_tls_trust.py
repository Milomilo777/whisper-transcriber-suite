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
from contextlib import contextmanager
from pathlib import Path

import certifi
import httpx
import pytest
import requests

from core import tls_trust
from core.server import tls as server_tls
from core.server.tls import generate_self_signed_cert

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture
def clean_env(monkeypatch, tmp_path):
    for name in ("SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "OPENSSL_WIN32_UTF8"):
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setenv("NO_PROXY", "*")
    monkeypatch.setattr(urllib.request, "_opener", None)
    monkeypatch.setattr(tls_trust, "source", "not configured")


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    """A stand-in for certifi's cacert.pem."""
    pem = tmp_path / "cacert.pem"
    pem.write_text("stand-in", encoding="ascii")
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
def test_windows_without_certifi_keeps_the_system_store(clean_env, monkeypatch, caplog, frozen):
    _platform(monkeypatch, "win32", frozen=frozen, default_has_certs=False)
    monkeypatch.setattr(tls_trust, "_certifi_file", lambda: None)
    assert tls_trust.configure() == "system"
    assert "SSL_CERT_FILE" not in os.environ
    assert "REQUESTS_CA_BUNDLE" not in os.environ
    assert len([entry for entry in caplog.records if entry.name == tls_trust.__name__]) == 1


@pytest.mark.parametrize("platform", ["darwin", "win32"])
@pytest.mark.parametrize("var", ["SSL_CERT_FILE", "SSL_CERT_DIR"])
def test_a_variable_the_user_set_is_never_overridden(clean_env, bundle, monkeypatch, var, platform):
    _platform(monkeypatch, platform, frozen=True, default_has_certs=False)
    monkeypatch.setenv(var, "/users/own/ca.pem")
    assert tls_trust.configure() == "env"
    assert os.environ[var] == "/users/own/ca.pem"
    if var == "SSL_CERT_DIR":
        assert "SSL_CERT_FILE" not in os.environ
    assert "REQUESTS_CA_BUNDLE" not in os.environ


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
    with _serve_https(cert, key) as url:
        yield url, str(cert)


@contextmanager
def _serve_https(cert, key):
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(cert), str(key))
    with http.server.HTTPServer(("127.0.0.1", 0), _Hello) as httpd:
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f"https://127.0.0.1:{httpd.server_address[1]}/"
        finally:
            httpd.shutdown()
            thread.join()


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


def _ca_der(path):
    return ssl.PEM_cert_to_DER_cert(path.read_text(encoding="ascii"))


@pytest.fixture
def test_roots(tmp_path, monkeypatch):
    """Generate independent trust anchors that can also serve loopback HTTPS."""
    extension = server_tls._extension

    def ca_extension(oid, value, *, critical=False):
        # The app generates server leaves. Mark these fixtures as CA certificates so
        # SSLContext.get_ca_certs() reports them and the union can deduplicate them.
        if oid == server_tls._OID_BASIC_CONSTRAINTS:
            value = server_tls._seq(server_tls._tlv(0x01, b"\xff"))  # cA = TRUE
        elif oid == server_tls._OID_KEY_USAGE:
            value = server_tls._tlv(0x03, b"\x02\x84")  # digitalSignature, keyCertSign
        return extension(oid, value, critical=critical)

    roots = {}
    with monkeypatch.context() as patch:
        patch.setattr(server_tls, "_extension", ca_extension)
        for name in ("windows", "certifi"):
            cert, key = tmp_path / f"{name}.pem", tmp_path / f"{name}.key"
            generate_self_signed_cert(cert, key, common_name=f"Test {name}", hosts=["127.0.0.1", "localhost"])
            roots[name] = cert, key
    return roots


@pytest.fixture
def windows_cas(clean_env, monkeypatch, test_roots):
    _platform(monkeypatch, "win32", frozen=False, default_has_certs=False)
    monkeypatch.setattr(certifi, "where", lambda: str(test_roots["certifi"][0]))
    windows_der = _ca_der(test_roots["windows"][0])
    records = {"ROOT": [], "CA": [(windows_der, "x509_asn", {ssl.Purpose.SERVER_AUTH.oid})]}
    monkeypatch.setattr(ssl, "enum_certificates", records.__getitem__, raising=False)
    return records


@pytest.mark.parametrize("store", ["ROOT", "CA"])
def test_windows_https_clients_trust_both_ca_sources(windows_cas, test_roots, monkeypatch, store):
    if store == "ROOT":
        windows_cas["ROOT"].append(windows_cas["CA"].pop())
    else:
        profile = Path(os.environ["WTS_PROFILE_DIR"]) / "\u0641\u0627\u0631\u0633\u06cc"
        monkeypatch.setenv("WTS_PROFILE_DIR", str(profile))
    expected = {_ca_der(cert) for cert, _ in test_roots.values()}
    assert len(expected) == 2
    source = tls_trust.configure()

    assert expected <= set(httpx.create_ssl_context().get_ca_certs(binary_form=True))
    assert expected <= set(ssl.create_default_context().get_ca_certs(binary_form=True))
    with requests.Session() as session:
        verify = session.merge_environment_settings("https://example.invalid/", {}, None, None, None)["verify"]
    assert verify == os.environ["SSL_CERT_FILE"]
    requests_ca_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    requests_ca_context.load_verify_locations(cafile=verify)
    assert expected == set(requests_ca_context.get_ca_certs(binary_form=True))
    assert source == "system+certifi"
    assert tls_trust.describe()["cafile"] == verify

    with httpx.Client(timeout=10) as httpx_client, requests.Session() as requests_client:
        for cert, key in test_roots.values():
            with _serve_https(cert, key) as url:
                assert httpx_client.get(url).content == b"hello"
                assert requests_client.get(url, timeout=10).content == b"hello"
                with urllib.request.urlopen(url, timeout=10) as response:
                    assert response.read() == b"hello"


def test_windows_bundle_keeps_distinct_server_auth_certificates(windows_cas, test_roots):
    windows_ca = _ca_der(test_roots["windows"][0])
    certifi_ca = _ca_der(test_roots["certifi"][0])
    windows_cas["ROOT"] = [(certifi_ca, "x509_asn", True), (windows_ca, "x509_asn", True)]
    windows_cas["CA"].extend([
        (b"client only", "x509_asn", {ssl.Purpose.CLIENT_AUTH.oid}),
        (b"not trusted", "x509_asn", False),
        (b"other encoding", "pkcs_7_asn", True),
    ])
    assert tls_trust.configure() == "system+certifi"
    pem = Path(os.environ["SSL_CERT_FILE"]).read_text(encoding="ascii")
    assert pem == ssl.DER_cert_to_PEM_cert(certifi_ca) + ssl.DER_cert_to_PEM_cert(windows_ca)


@pytest.mark.parametrize(("override", "other"), [
    ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"),
    ("CURL_CA_BUNDLE", "REQUESTS_CA_BUNDLE"),
])
def test_windows_preserves_requests_ca_overrides(windows_cas, test_roots, monkeypatch, override, other):
    path = str(test_roots["certifi"][0])
    monkeypatch.setenv(override, path)
    assert tls_trust.configure() == "system+certifi"
    assert os.environ[override] == path
    assert other not in os.environ
    assert os.environ["SSL_CERT_FILE"] != path
    with requests.Session() as session:
        assert session.merge_environment_settings("https://example.invalid/", {}, None, None, None)["verify"] == path


def test_windows_bundle_write_failure_keeps_the_system_store(windows_cas, monkeypatch, caplog):
    old_bundle = Path(os.environ["WTS_PROFILE_DIR"]) / "cache" / "https-ca-bundle.pem"
    old_bundle.parent.mkdir(parents=True)
    old_bundle.write_bytes(b"earlier cache contents")

    def cannot_replace(_source, _destination):
        raise PermissionError("simulated read-only destination")

    monkeypatch.setattr(os, "replace", cannot_replace)
    assert tls_trust.configure() == "system"
    assert "SSL_CERT_FILE" not in os.environ
    assert "REQUESTS_CA_BUNDLE" not in os.environ
    assert old_bundle.read_bytes() == b"earlier cache contents"
    assert not list(old_bundle.parent.glob("*.tmp"))
    warnings = [entry for entry in caplog.records if entry.name == tls_trust.__name__]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"


def test_windows_invalid_store_certificate_keeps_the_system_store(windows_cas, caplog):
    windows_cas["CA"].append((b"invalid DER", "x509_asn", True))
    assert tls_trust.configure() == "system"
    assert "SSL_CERT_FILE" not in os.environ
    assert "REQUESTS_CA_BUNDLE" not in os.environ
    assert len([entry for entry in caplog.records if entry.name == tls_trust.__name__]) == 1


def test_windows_worker_inherits_the_ca_bundle(windows_cas, test_roots, monkeypatch):
    profile = Path(os.environ["WTS_PROFILE_DIR"]) / "\u0641\u0627\u0631\u0633\u06cc"
    monkeypatch.setenv("WTS_PROFILE_DIR", str(profile))
    assert tls_trust.configure() == "system+certifi"
    script = """
import json
import os
import ssl

certs = ssl.create_default_context().get_ca_certs(binary_form=True)
print(json.dumps([os.environ["SSL_CERT_FILE"], os.environ["REQUESTS_CA_BUNDLE"], [der.hex() for der in certs]]))
"""
    result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True, timeout=30)
    cafile, requests_bundle, certs = json.loads(result.stdout)
    assert cafile == requests_bundle == os.environ["SSL_CERT_FILE"]
    assert {_ca_der(cert).hex() for cert, _ in test_roots.values()} <= set(certs)


def test_windows_verified_fetches_use_the_bundle_after_startup(clean_env, test_roots):
    script = """
import http.client
import ssl
import sys
from pathlib import Path

import certifi
from core import tls_trust

sys.platform = "win32"
ssl.enum_certificates = lambda store: []
certifi.where = lambda: sys.argv[1]
assert tls_trust.configure() == "system+certifi"

from core.verified_download import urlopen_https_only

class ContextChecked(Exception):
    pass

def check_context(connection):
    cert = ssl.PEM_cert_to_DER_cert(Path(sys.argv[1]).read_text(encoding="ascii"))
    assert cert in connection._context.get_ca_certs(binary_form=True)
    raise ContextChecked

http.client.HTTPSConnection.connect = check_context
try:
    urlopen_https_only("https://example.invalid/", timeout=10)
except ContextChecked:
    pass
else:
    raise AssertionError("HTTPS connection did not use the context")
"""
    result = subprocess.run([sys.executable, "-c", script, str(test_roots["certifi"][0])], cwd=REPO,
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr


def test_self_check_flag_prints_the_choice_and_exits(clean_env):
    env = {k: v for k, v in os.environ.items() if k not in ("SSL_CERT_FILE", "SSL_CERT_DIR")}
    out = subprocess.run([sys.executable, str(REPO / "gui.py"), "--tls-self-check"], cwd=REPO, env=env,
                         capture_output=True, text=True, timeout=120, check=True).stdout
    info = json.loads(out.strip().splitlines()[-1])
    assert info["source"] in {"system+certifi", "system", "certifi", "none"}
    assert set(info) >= {"cafile", "capath", "openssl_cafile", "openssl"}
    if info["source"] == "system+certifi":
        expected = Path(os.environ["WTS_PROFILE_DIR"]) / "cache" / "https-ca-bundle.pem"
        assert Path(info["cafile"]) == expected
        assert expected.is_file()


def test_a_child_process_inherits_the_choice(clean_env, bundle, monkeypatch):
    _platform(monkeypatch, "darwin", frozen=True, default_has_certs=False)
    tls_trust.configure()
    out = subprocess.run([sys.executable, "-c", "import os; print(os.environ.get('SSL_CERT_FILE'))"],
                         capture_output=True, text=True, timeout=60, check=True).stdout.strip()
    assert out == bundle
