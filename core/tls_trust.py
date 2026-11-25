"""Which CA certificates the app's HTTPS requests trust.

The macOS app is frozen from python.org's Python, whose OpenSSL looks for its CA file under the build
machine's ``/Library/Frameworks/Python.framework/.../etc/openssl``. On a user's Mac that file does not
exist, so every request made through ``urllib`` (update check, usage statistics, problem reports,
web lookups) failed with ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``, while
the build machine, which has the file, worked. ``requests`` and ``huggingface_hub`` were not affected:
they use certifi's bundle on their own.

:func:`configure` runs at process start (``gui.py``) before the first HTTPS request. New contexts
load their default trust from ``SSL_CERT_FILE`` where set, and worker processes inherit the setting.
Since Python 3.13 urllib's shared opener keeps the SSL context it made first.

- A ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` the user has set is never touched.
- Windows: combine the Windows ROOT and CA stores with certifi for OpenSSL, HTTPX and Requests.
- Frozen macOS build: always certifi; the default path belongs to the build machine.
- Elsewhere (Linux, macOS from source): the default store when it holds certificates (a Linux
  distribution's store also carries local corporate CAs), else certifi.
"""

from __future__ import annotations

import logging
import os
import ssl
import sys
import tempfile
from pathlib import Path

from core.paths import user_cache_dir

_ENV_FILE = "SSL_CERT_FILE"
_ENV_DIR = "SSL_CERT_DIR"
_REQUESTS_FILE = "REQUESTS_CA_BUNDLE"
_CURL_FILE = "CURL_CA_BUNDLE"
_WINDOWS_UTF8 = "OPENSSL_WIN32_UTF8"

logger = logging.getLogger(__name__)

# What configure() chose in this process, for diagnostics ("--tls-self-check").
source = "not configured"


def _certifi_file() -> str | None:
    try:
        import certifi  # noqa: PLC0415 - optional at import time; requests depends on it
    except ImportError:
        return None
    path = certifi.where()
    try:
        return path if os.path.getsize(path) > 0 else None
    except OSError:
        return None


def _default_store_has_certs() -> bool:
    """True when OpenSSL's default CA file or directory (as compiled in) holds anything."""
    paths = ssl.get_default_verify_paths()
    cafile = paths.openssl_cafile
    try:
        if cafile and os.path.getsize(cafile) > 0:
            return True
    except OSError:
        pass
    capath = paths.openssl_capath
    try:
        return bool(capath) and any(os.scandir(capath))
    except OSError:
        return False


def _use_certifi() -> str:
    path = _certifi_file()
    if path is None:
        return "none"
    os.environ[_ENV_FILE] = path
    return "certifi"


def _windows_pem(certifi_path: str) -> bytes:
    """Keep certifi's PEM and append each distinct Windows server-auth certificate."""
    certifi_pem = Path(certifi_path).read_text(encoding="ascii")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.load_verify_locations(cadata=certifi_pem)
    certifi_certs = set(context.get_ca_certs(binary_form=True))
    if not certifi_certs:
        raise ValueError("certifi bundle contains no CA certificates")

    # Windows-only in the standard library; looked up at run time so type checks pass on every OS.
    enum_certificates = getattr(ssl, "enum_certificates", None)
    if enum_certificates is None:
        raise RuntimeError("Windows certificate store enumeration is unavailable")
    windows_certs = set()
    for store in ("ROOT", "CA"):
        for der, encoding, trust in enum_certificates(store):
            server_auth = trust is True or (isinstance(trust, set) and ssl.Purpose.SERVER_AUTH.oid in trust)
            if encoding == "x509_asn" and server_auth:
                windows_certs.add(der)
    extra_pem = "".join(ssl.DER_cert_to_PEM_cert(der) for der in sorted(windows_certs - certifi_certs))
    if extra_pem:
        # Validate the Windows additions before publishing trust settings for the clients.
        context.load_verify_locations(cadata=extra_pem)
    return (certifi_pem.rstrip() + "\n" + extra_pem).encode("ascii")


def _write_windows_bundle(path: Path, pem: bytes) -> None:
    try:
        if path.read_bytes() == pem:
            return
    except FileNotFoundError:
        pass

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, staged = tempfile.mkstemp(dir=path.parent, prefix=".https-ca-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as file:
            file.write(pem)
        os.replace(staged, path)
    finally:
        Path(staged).unlink(missing_ok=True)


def _use_windows_bundle() -> str:
    try:
        certifi_path = _certifi_file()
        if certifi_path is None:
            raise FileNotFoundError("certifi bundle is unavailable")
        path = (user_cache_dir() / "https-ca-bundle.pem").absolute()
        _write_windows_bundle(path, _windows_pem(certifi_path))
    except (OSError, ValueError, RuntimeError) as exc:
        logger.warning("Windows HTTPS CA bundle unavailable. Using default trust (%s).", exc)
        return "system"

    bundle = str(path)
    if not bundle.isascii():
        # OpenSSL otherwise reads SSL_CERT_FILE through the Windows ANSI code page.
        os.environ.setdefault(_WINDOWS_UTF8, "1")
    os.environ[_ENV_FILE] = bundle
    if _REQUESTS_FILE not in os.environ and _CURL_FILE not in os.environ:
        os.environ[_REQUESTS_FILE] = bundle
    return "system+certifi"


def configure() -> str:
    """Pick the CA source for this process (see the module docstring) and return its name:
    ``env``, ``system+certifi``, ``system``, ``certifi`` or ``none`` (nothing usable)."""
    global source
    if os.environ.get(_ENV_FILE) or os.environ.get(_ENV_DIR):
        source = "env"
    elif sys.platform == "win32":
        source = _use_windows_bundle()
    elif sys.platform == "darwin" and getattr(sys, "frozen", False):
        source = _use_certifi()
    elif _default_store_has_certs():
        source = "system"
    else:
        source = _use_certifi()
    return source


def describe() -> dict[str, str | None]:
    """The chosen source and the CA file/dir a new SSL context will load."""
    paths = ssl.get_default_verify_paths()
    return {
        "source": source,
        "cafile": paths.cafile,
        "capath": paths.capath,
        "openssl_cafile": paths.openssl_cafile,
        "openssl": ssl.OPENSSL_VERSION,
    }
