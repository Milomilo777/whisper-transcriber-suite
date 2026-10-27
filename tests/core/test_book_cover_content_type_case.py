"""A cover reply's Content-Type must be matched case-insensitively.

RFC 9110 section 8.3: media types are case-insensitive — a
standards-compliant server may answer ``Image/JPEG`` or ``image/JPEG``.
``fetch_cover`` compared ``ctype.startswith("image/")`` verbatim, so such a
reply raised ``BookCoverError("The cover reply is not a picture")`` even
though the bytes were a valid JPEG and the panel showed the placeholder
forever.

Hermetic: fake urlopen, tmp cache dir, no network, no PIL.
"""
from __future__ import annotations

from typing import Any

import pytest

from core.integrations import smtv_books as sb

_JPEG = b"\xff\xd8\xff" + b"body-of-a-jpeg"


class _Resp:
    def __init__(self, body: bytes, content_type: str) -> None:
        self._body = body
        self.headers = {"Content-Type": content_type}

    def read(self, n: int = -1) -> bytes:
        return self._body if n < 0 else self._body[:n]

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *_a: Any) -> None:
        return None


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(sb, "cache_dir", lambda: tmp_path)
    return tmp_path


@pytest.mark.parametrize("content_type", ["Image/JPEG", "image/JPEG", "IMAGE/JPEG"])
def test_cover_accepts_any_content_type_case(cache, monkeypatch, content_type):
    def fake_urlopen(req, timeout=None):
        return _Resp(_JPEG, content_type)

    monkeypatch.setattr(sb.urllib.request, "urlopen", fake_urlopen)
    assert sb.fetch_cover(sb.BOOKS[0]) == _JPEG
