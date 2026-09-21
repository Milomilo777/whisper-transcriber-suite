"""Self-signed TLS certificate for the optional HTTPS server.

The LAN/web server is plain HTTP by default. Turning HTTPS on needs a
certificate, and this app has no third-party dependency it can lean on to
mint one (``cryptography`` is deliberately not a runtime requirement, and
``openssl`` is not guaranteed to exist on a Windows install). So this module
generates a self-signed P-256 (ECDSA) certificate with nothing but the
standard library: a tiny DER/ASN.1 encoder plus the P-256 curve arithmetic
needed to produce the key pair and the ECDSA signature.

The certificate + key live under ``user_data_dir()/server/`` and are
REUSED on every later start; they are only regenerated when the pair is
missing or fails to load (e.g. hand-edited / truncated). It is self-signed,
so browsers show the usual "not trusted" warning until the user accepts it —
that is the expected behaviour for a LAN convenience server, and the docs
say so.

Stdlib only. Tk-free. Imports nothing from ``app/``.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import ipaddress
import logging
import os
import secrets
import socket
import ssl
import tempfile
from pathlib import Path

from core.config import user_data_dir

logger = logging.getLogger(__name__)

__all__ = [
    "cert_dir",
    "cert_path",
    "key_path",
    "ensure_certificate",
    "build_server_ssl_context",
    "generate_self_signed_cert",
]

# How long a generated certificate is valid. Long by design: the file is
# reused indefinitely, and a browser warning on an expired self-signed cert
# would be one more confusing step for a non-technical user.
_CERT_DAYS = 3650

# P-256 (secp256r1) domain parameters — FIPS 186-4 / SEC 2.
_P = 0xFFFFFFFF00000001000000000000000000000000FFFFFFFFFFFFFFFFFFFFFFFF
_A = _P - 3
_B = 0x5AC635D8AA3A93E7B3EBBD55769886BC651D06B0CC53B0F63BCE3C3E27D2604B
_GX = 0x6B17D1F2E12C4247F8BCE6E563A440F277037D812DEB33A0F4A13945D898C296
_GY = 0x4FE342E2FE1A7F9B8EE7EB4A7C0F9E162BCE33576B315ECECBB6406837BF51F5
_N = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551

# DER-encoded object identifiers (the value bytes, without tag/length).
_OID_EC_PUBLIC_KEY = bytes.fromhex("2a8648ce3d0201")      # 1.2.840.10045.2.1
_OID_PRIME256V1 = bytes.fromhex("2a8648ce3d030107")       # 1.2.840.10045.3.1.7
_OID_ECDSA_SHA256 = bytes.fromhex("2a8648ce3d040302")     # 1.2.840.10045.4.3.2
_OID_CN = bytes.fromhex("550403")                          # 2.5.4.3
_OID_SUBJECT_ALT_NAME = bytes.fromhex("551d11")            # 2.5.29.17
_OID_BASIC_CONSTRAINTS = bytes.fromhex("551d13")           # 2.5.29.19
_OID_KEY_USAGE = bytes.fromhex("551d0f")                   # 2.5.29.15
_OID_EXT_KEY_USAGE = bytes.fromhex("551d25")               # 2.5.29.37
_OID_SERVER_AUTH = bytes.fromhex("2b06010505070301")       # 1.3.6.1.5.5.7.3.1


# --- minimal DER encoding helpers --------------------------------------------

def _der_length(length: int) -> bytes:
    if length < 0x80:
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(value)) + value


def _seq(*parts: bytes) -> bytes:
    return _tlv(0x30, b"".join(parts))


def _set(*parts: bytes) -> bytes:
    return _tlv(0x31, b"".join(parts))


def _der_int(value: int) -> bytes:
    if value <= 0:
        return _tlv(0x02, b"\x00")
    # ``(bit_length + 8) // 8`` rounds up AND reserves a leading zero byte
    # when the top bit is set, keeping the INTEGER positive in two's
    # complement.
    raw = value.to_bytes((value.bit_length() + 8) // 8, "big")
    return _tlv(0x02, raw)


def _oid(value: bytes) -> bytes:
    return _tlv(0x06, value)


def _utf8(value: str) -> bytes:
    return _tlv(0x0C, value.encode("utf-8"))


def _utc_time(when: _dt.datetime) -> bytes:
    # UTCTime covers 1950-2049; our validity window is well inside that.
    stamp = when.strftime("%y%m%d%H%M%SZ").encode("ascii")
    return _tlv(0x17, stamp)


def _bit_string(data: bytes) -> bytes:
    return _tlv(0x03, b"\x00" + data)


def _octet_string(data: bytes) -> bytes:
    return _tlv(0x04, data)


def _explicit(tag: int, value: bytes) -> bytes:
    return _tlv(0xA0 | tag, value)


def _pem(label: str, der: bytes) -> str:
    body = base64.b64encode(der).decode("ascii")
    lines = [body[i:i + 64] for i in range(0, len(body), 64)]
    return (
        f"-----BEGIN {label}-----\n"
        + "\n".join(lines)
        + f"\n-----END {label}-----\n"
    )


# --- P-256 arithmetic --------------------------------------------------------

_Point = tuple[int, int] | None


def _point_add(p1: _Point, p2: _Point) -> _Point:
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    x1, y1 = p1
    x2, y2 = p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        slope = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    y3 = (slope * (x1 - x3) - y1) % _P
    return (x3, y3)


def _point_mul(k: int, point: _Point) -> _Point:
    result: _Point = None
    addend = point
    while k:
        if k & 1:
            result = _point_add(result, addend)
        addend = _point_add(addend, addend)
        k >>= 1
    return result


def _generate_keypair() -> tuple[int, tuple[int, int]]:
    """A fresh P-256 private scalar + public point."""
    private = secrets.randbelow(_N - 1) + 1
    public = _point_mul(private, (_GX, _GY))
    if public is None:  # pragma: no cover - impossible for a valid scalar
        raise RuntimeError("EC key generation failed")
    return private, public


def _ecdsa_sign(private: int, digest: bytes) -> bytes:
    """ECDSA-SHA256 signature over ``digest`` as a DER SEQUENCE{r,s}."""
    e = int.from_bytes(digest, "big")
    while True:
        k = secrets.randbelow(_N - 1) + 1
        point = _point_mul(k, (_GX, _GY))
        if point is None:  # pragma: no cover
            continue
        r = point[0] % _N
        if r == 0:
            continue
        s = (pow(k, -1, _N) * (e + r * private)) % _N
        if s == 0:
            continue
        return _seq(_der_int(r), _der_int(s))


# --- X.509 construction ------------------------------------------------------

def _name(common_name: str) -> bytes:
    return _seq(_set(_seq(_oid(_OID_CN), _utf8(common_name))))


def _general_name(host: str) -> bytes | None:
    """A SAN GeneralName for ``host`` (IP or DNS), or None when unusable."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        return _tlv(0x87, ip.packed)  # context [7] iPAddress
    name = host.strip()
    if not name:
        return None
    try:
        name = name.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    if len(name) > 253:
        return None
    return _tlv(0x82, name.encode("ascii"))  # context [2] dNSName


def _extension(oid: bytes, value: bytes, *, critical: bool = False) -> bytes:
    parts = [_oid(oid)]
    if critical:
        parts.append(_tlv(0x01, b"\xff"))
    parts.append(_octet_string(value))
    return _seq(*parts)


def _subject_alt_name(hosts: list[str]) -> bytes:
    names = [gn for gn in (_general_name(h) for h in hosts) if gn is not None]
    if not names:
        names = [_tlv(0x82, b"localhost")]
    return _seq(*names)


def _build_certificate(
    private: int, public: tuple[int, int], common_name: str,
    hosts: list[str], days: int,
) -> bytes:
    x, y = public
    now = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    not_before = now - _dt.timedelta(days=1)  # tolerate client clock skew
    not_after = now + _dt.timedelta(days=days)

    spki = _seq(
        _seq(_oid(_OID_EC_PUBLIC_KEY), _oid(_OID_PRIME256V1)),
        _bit_string(b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big")),
    )
    extensions = _explicit(3, _seq(
        # cA defaults to FALSE, and DER requires default values be omitted —
        # so the basicConstraints value is an empty SEQUENCE.
        _extension(_OID_BASIC_CONSTRAINTS, _seq(), critical=True),
        # keyUsage: digitalSignature (bit 0).
        _extension(_OID_KEY_USAGE, _tlv(0x03, b"\x07\x80"), critical=True),
        _extension(_OID_EXT_KEY_USAGE, _seq(_oid(_OID_SERVER_AUTH))),
        _extension(_OID_SUBJECT_ALT_NAME, _subject_alt_name(hosts)),
    ))
    tbs = _seq(
        _explicit(0, _der_int(2)),               # version v3
        _der_int(secrets.randbits(63) | 1),      # serialNumber
        _seq(_oid(_OID_ECDSA_SHA256)),           # signature algorithm
        _name(common_name),                      # issuer
        _seq(_utc_time(not_before), _utc_time(not_after)),
        _name(common_name),                      # subject
        spki,
        extensions,
    )
    signature = _ecdsa_sign(private, hashlib.sha256(tbs).digest())
    return _seq(tbs, _seq(_oid(_OID_ECDSA_SHA256)), _bit_string(signature))


def _build_private_key_pem(private: int, public: tuple[int, int]) -> str:
    x, y = public
    ec_private_key = _seq(
        _der_int(1),
        _octet_string(private.to_bytes(32, "big")),
        _explicit(0, _oid(_OID_PRIME256V1)),
        _explicit(1, _bit_string(
            b"\x04" + x.to_bytes(32, "big") + y.to_bytes(32, "big"))),
    )
    pkcs8 = _seq(
        _der_int(0),
        _seq(_oid(_OID_EC_PUBLIC_KEY), _oid(_OID_PRIME256V1)),
        _octet_string(ec_private_key),
    )
    return _pem("PRIVATE KEY", pkcs8)


# --- public API --------------------------------------------------------------

def cert_dir() -> Path:
    """Directory that holds the server's self-signed certificate + key."""
    return user_data_dir() / "server"


def cert_path() -> Path:
    return cert_dir() / "server_cert.pem"


def key_path() -> Path:
    return cert_dir() / "server_key.pem"


def _default_san_hosts() -> list[str]:
    """Names/IPs to embed as subjectAltName entries.

    A self-signed certificate is accepted manually, so a SAN mismatch only
    changes the browser warning text — but matching the usual addresses
    (localhost + this machine's name + its primary LAN IP) keeps the
    "certificate is for a different site" variant out of the way.
    """
    hosts = ["localhost", "127.0.0.1", "::1"]
    try:
        name = socket.gethostname()
    except OSError:
        name = ""
    if name and name.isascii():
        hosts.append(name)
    try:
        # Imported lazily to avoid an import cycle: core.server imports this
        # module for the HTTPS start path.
        from core.server import _primary_lan_ip
        lan_ip = _primary_lan_ip()
    except Exception:  # noqa: BLE001 - best-effort only
        lan_ip = ""
    if lan_ip:
        hosts.append(lan_ip)
    # De-dupe while keeping order.
    seen: set[str] = set()
    return [h for h in hosts if not (h in seen or seen.add(h))]


def _write_atomic(path: Path, text: str, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=path.name, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="ascii", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
        try:
            os.chmod(path, mode)
        except OSError:
            pass  # Windows / FAT: permissions are advisory here anyway
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def generate_self_signed_cert(
    cert_file: str | os.PathLike[str],
    key_file: str | os.PathLike[str],
    *,
    common_name: str = "Whisper Transcriber Suite",
    hosts: list[str] | None = None,
    days: int = _CERT_DAYS,
) -> None:
    """Write a fresh self-signed certificate + private key (PEM files)."""
    private, public = _generate_keypair()
    cert_der = _build_certificate(
        private, public, common_name,
        hosts if hosts is not None else _default_san_hosts(), days,
    )
    cert_pem = ssl.DER_cert_to_PEM_cert(cert_der)
    key_pem = _build_private_key_pem(private, public)
    _write_atomic(Path(key_file), key_pem, mode=0o600)
    _write_atomic(Path(cert_file), cert_pem, mode=0o644)


def _pair_loads(cert_file: Path, key_file: Path) -> bool:
    """True iff both PEM files exist and OpenSSL accepts them as a pair."""
    if not cert_file.is_file() or not key_file.is_file():
        return False
    try:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=str(cert_file), keyfile=str(key_file))
    except (OSError, ssl.SSLError, ValueError):
        return False
    return True


def ensure_certificate(
    cert_file: str | os.PathLike[str] | None = None,
    key_file: str | os.PathLike[str] | None = None,
) -> tuple[str, str]:
    """Return ``(cert_path, key_path)``, generating the pair when needed.

    Reuses an existing pair as long as OpenSSL can load it; a missing or
    unreadable pair (first run, a hand-edited file, a truncated download)
    is regenerated in place.
    """
    cert = Path(cert_file) if cert_file is not None else cert_path()
    key = Path(key_file) if key_file is not None else key_path()
    if _pair_loads(cert, key):
        return str(cert), str(key)
    logger.info("server: generating a self-signed certificate at %s", cert)
    try:
        generate_self_signed_cert(cert, key)
    except OSError as e:
        raise RuntimeError(
            f"could not write the HTTPS certificate to {cert.parent}: {e}"
        ) from e
    return str(cert), str(key)


def build_server_ssl_context(
    cert_file: str | os.PathLike[str] | None = None,
    key_file: str | os.PathLike[str] | None = None,
) -> ssl.SSLContext:
    """An ``ssl.SSLContext`` for the job server, generating a cert if needed.

    Raises ``RuntimeError`` when no usable certificate can be produced, so
    an explicitly requested HTTPS start fails loudly instead of silently
    falling back to plaintext.
    """
    cert, key = ensure_certificate(cert_file, key_file)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        context.load_cert_chain(certfile=cert, keyfile=key)
    except (OSError, ssl.SSLError) as e:  # pragma: no cover - ensure_certificate ran
        raise RuntimeError(f"could not load the HTTPS certificate: {e}") from e
    return context
