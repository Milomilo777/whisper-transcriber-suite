"""Phone link for Web / LAN access: the page's network address and its QR code.

The Web / LAN access tab shows a QR code while the server is shared on the
local network, so a phone on the same Wi-Fi opens the page by scanning it.
With an access password the link carries it as ``?token=``, the same form the
page's own download links use; the page moves it out of the address bar
(``core/server/static/index.html``).
"""
from __future__ import annotations

import base64
import io
import logging
import urllib.parse

logger = logging.getLogger(__name__)


def phone_url(network_url: str, token: str = "") -> str:
    """``network_url`` plus ``token=<password>`` when a password is set."""
    token = token.strip()
    if not token:
        return network_url
    sep = "&" if "?" in network_url else "?"
    # quote everything: URLSearchParams on the page would read a bare "+" as a space
    return f"{network_url}{sep}token={urllib.parse.quote(token, safe='')}"


def qr_png_base64(text: str, scale: int = 4, border: int = 2) -> str:
    """The QR code of ``text`` as base64 PNG data for ``tk.PhotoImage(data=...)``.

    Returns "" when the ``segno`` package is missing; the tab then shows the
    link as text only. Always a regular QR code: phone cameras do not read the
    Micro QR codes segno picks for short input by default.
    """
    try:
        import segno  # noqa: PLC0415 - optional at runtime
    except ImportError:
        logger.info("QR code unavailable: the segno package is not installed")
        return ""
    buf = io.BytesIO()
    segno.make_qr(text, error="m").save(buf, kind="png", scale=scale, border=border,
                                        dark="#000000", light="#ffffff")
    return base64.b64encode(buf.getvalue()).decode("ascii")
