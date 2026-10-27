"""A cover refresh that gets a bad reply keeps the stale cached cover.

``fetch_cover``'s contract: "An older one is refreshed when the network
allows it and kept when it does not." The code only honoured that for
``OSError``; a 200 reply that is not a picture — the captive-portal /
parked-domain redirect every hotel Wi-Fi produces — raised
``BookCoverError`` and threw away the good cover still sitting in the
cache, so the panel lost its picture the moment a refresh went wrong.

Hermetic: fake urlopen, tmp cache dir, no network, no PIL.
"""
from __future__ import annotations

import os
import time
from typing import Any

import pytest

from core.integrations import smtv_books as sb

_STALE_JPEG = b"\xff\xd8\xff" + b"the-cached-cover"


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


def _seed_stale_cover(book: sb.Book, cache_dir) -> bytes:
    path = cache_dir / f"{book.key}.jpg"
    path.write_bytes(_STALE_JPEG)
    old = time.time() - 40 * 86400  # past the 30-day refresh age
    os.utime(path, (old, old))
    return _STALE_JPEG


def test_an_html_reply_keeps_the_stale_cached_cover(cache, monkeypatch):
    book = sb.BOOKS[0]
    stale = _seed_stale_cover(book, cache)

    def fake_urlopen(req, timeout=None):
        return _Resp(b"<html>Sign in to the captive portal</html>", "text/html")

    monkeypatch.setattr(sb.urllib.request, "urlopen", fake_urlopen)
    assert sb.fetch_cover(book) == stale


def test_an_oversized_reply_keeps_the_stale_cached_cover(cache, monkeypatch):
    book = sb.BOOKS[1]
    stale = _seed_stale_cover(book, cache)

    def fake_urlopen(req, timeout=None):
        return _Resp(b"\xff\xd8\xff" + b"x" * 3_000_000, "image/jpeg")

    monkeypatch.setattr(sb.urllib.request, "urlopen", fake_urlopen)
    assert sb.fetch_cover(book) == stale
