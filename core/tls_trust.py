"""Which CA certificates the app's HTTPS requests trust.

The macOS app is frozen from python.org's Python, whose OpenSSL looks for its CA file under the build
machine's ``/Library/Frameworks/Python.framework/.../etc/openssl``. On a user's Mac that file does not
exist, so every request made through ``urllib`` (update check, usage statistics, problem reports,
web lookups) failed with ``CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate``, while
the build machine, which has the file, worked. ``requests`` and ``huggingface_hub`` were not affected:
they use certifi's bundle on their own.

:func:`configure` runs once at process start (``gui.py``), before any request, and points OpenSSL at
certifi's bundle (shipped inside the app) through ``SSL_CERT_FILE`` where the default store is not
reliable. OpenSSL reads that variable each time a context loads its default paths, so every caller is
covered, and the worker processes the app starts inherit it. It must run before the first
``urlopen``: since Python 3.13 urllib's shared opener keeps the SSL context it made first.

- A ``SSL_CERT_FILE`` / ``SSL_CERT_DIR`` the user has set is never touched.
- Windows: left alone; Python reads the Windows certificate store there.
- Frozen macOS build: always certifi; the default path belongs to the build machine.
- Elsewhere (Linux, macOS from source): the default store when it holds certificates (a Linux
  distribution's store also carries local corporate CAs), else certifi.
"""

from __future__ import annotations

import os
import ssl
import sys

_ENV_FILE = "SSL_CERT_FILE"
_ENV_DIR = "SSL_CERT_DIR"

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


def configure() -> str:
    """Pick the CA source for this process (see the module docstring) and return its name:
    ``env`` (the user's own variable), ``system``, ``certifi`` or ``none`` (nothing usable)."""
    global source
    if os.environ.get(_ENV_FILE) or os.environ.get(_ENV_DIR):
        source = "env"
    elif sys.platform == "win32":
        source = "system"
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
