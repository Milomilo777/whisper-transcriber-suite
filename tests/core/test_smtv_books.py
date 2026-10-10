"""The two book showcases of the Supreme Master TV tab: data and cover download (no network)."""
from __future__ import annotations

import io
import os
import time
import urllib.parse
from typing import Any

import pytest

from core import offline
from core.integrations import smtv_books as sb


def _jpeg() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "JPEG")
    return buf.getvalue()


class _Resp:
    def __init__(self, body: bytes, content_type: str = "image/jpeg") -> None:
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


# ------------------------------------------------------------------ data

def test_the_books_with_the_official_titles_and_pages():
    assert [b.title for b in sb.BOOKS] == [
        "From Crisis to Peace", "Love Is The Only Solution", "More e-books"]
    crisis, love, more = sb.BOOKS
    assert more.official_url == (
        "https://smchbooks.com/index.php?route=product/category&path=61")
    assert [link.url for link in more.links] == [more.official_url]
    assert crisis.subtitle == "The Organic Vegan Way is the Answer"
    assert love.subtitle == ""
    assert crisis.official_url == "https://crisis2peace.org/"
    assert love.official_url == (
        "https://smchbooks.com/index.php?route=product/product&product_id=1154")
    for book in sb.BOOKS:
        assert book.author == "Supreme Master Ching Hai"
        assert book.summary and book.facts


def test_every_link_and_cover_is_https_on_an_official_host():
    for book in sb.BOOKS:
        urls = [book.cover_url, *(link.url for link in book.links)]
        for url in urls:
            parts = urllib.parse.urlsplit(url)
            assert parts.scheme == "https", url
            assert parts.hostname in sb.ALLOWED_HOSTS, url
        assert book.links[-1].url == book.official_url
        assert sum(link.primary for link in book.links) == 1


def test_free_pdf_links_point_at_the_english_files():
    crisis, love, _more = sb.BOOKS
    assert any(link.url.endswith("From-Crisis-to-Peace-English-S-2025-02-12.pdf")
               for link in crisis.links)
    assert any(link.url == "https://smchbooks.com/ebook/data/english/E-LoveistheOnly.pdf"
               for link in love.links)


def test_find_by_title_and_unknown_title():
    assert sb.find("Love Is The Only Solution") is sb.BOOKS[1]
    assert sb.find("No such book") is None


# ---------------------------------------------------------------- covers

def test_cover_is_downloaded_once_then_read_from_the_cache(cache, monkeypatch):
    calls: list[str] = []

    def fake_urlopen(req, timeout=None):
        calls.append(req.full_url)
        return _Resp(_jpeg())

    monkeypatch.setattr(sb.urllib.request, "urlopen", fake_urlopen)
    book = sb.BOOKS[0]
    first = sb.fetch_cover(book)
    assert first == _jpeg() and calls == [book.cover_url]
    assert (cache / f"{book.key}.jpg").read_bytes() == first
    assert sb.fetch_cover(book) == first
    assert len(calls) == 1   # second call served from the cache


def test_offline_makes_no_request_and_reports_the_switch(cache, monkeypatch):
    def boom(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("network primitive called while offline")

    monkeypatch.setattr(sb.urllib.request, "urlopen", boom)
    offline.set_offline(True)
    with pytest.raises(offline.OfflineModeError, match="Offline mode is on"):
        sb.fetch_cover(sb.BOOKS[1])
    assert list(cache.iterdir()) == []


def test_offline_still_shows_a_cover_that_is_already_cached(cache, monkeypatch):
    monkeypatch.setattr(sb.urllib.request, "urlopen", lambda *_a, **_k: _Resp(_jpeg()))
    sb.fetch_cover(sb.BOOKS[0])
    path = cache / f"{sb.BOOKS[0].key}.jpg"
    old = time.time() - 90 * 86400
    os.utime(path, (old, old))            # stale: would normally be refreshed
    offline.set_offline(True)
    monkeypatch.setattr(sb.urllib.request, "urlopen",
                        lambda *_a, **_k: pytest.fail("request while offline"))
    assert sb.fetch_cover(sb.BOOKS[0]) == _jpeg()


def test_stale_cache_is_kept_when_the_refresh_fails(cache, monkeypatch):
    monkeypatch.setattr(sb.urllib.request, "urlopen", lambda *_a, **_k: _Resp(_jpeg()))
    sb.fetch_cover(sb.BOOKS[0])
    path = cache / f"{sb.BOOKS[0].key}.jpg"
    old = time.time() - 90 * 86400
    os.utime(path, (old, old))

    def fail(*_a: Any, **_k: Any) -> Any:
        raise OSError("network down")

    monkeypatch.setattr(sb.urllib.request, "urlopen", fail)
    assert sb.fetch_cover(sb.BOOKS[0]) == _jpeg()


def test_failed_download_without_a_cache_raises(cache, monkeypatch):
    def fail(*_a: Any, **_k: Any) -> Any:
        raise OSError("network down")

    monkeypatch.setattr(sb.urllib.request, "urlopen", fail)
    with pytest.raises(OSError):
        sb.fetch_cover(sb.BOOKS[0])
    assert list(cache.iterdir()) == []


@pytest.mark.parametrize("body, ctype", [
    (b"<html>not an image</html>", "text/html"),
    (b"x" * 100, "image/jpeg"),
])
def test_a_reply_that_is_not_an_image_is_refused_and_not_cached(cache, monkeypatch, body, ctype):
    monkeypatch.setattr(sb.urllib.request, "urlopen", lambda *_a, **_k: _Resp(body, ctype))
    with pytest.raises(sb.BookCoverError):
        sb.fetch_cover(sb.BOOKS[0])
    assert list(cache.iterdir()) == []


def test_an_oversized_reply_is_refused(cache, monkeypatch):
    big = _jpeg() + b"\0" * 5000
    monkeypatch.setattr(sb.urllib.request, "urlopen", lambda *_a, **_k: _Resp(big))
    with pytest.raises(sb.BookCoverError, match="too large"):
        sb.fetch_cover(sb.BOOKS[0], limit=1000)


def test_a_cover_url_off_the_official_hosts_is_never_requested(cache, monkeypatch):
    monkeypatch.setattr(sb.urllib.request, "urlopen",
                        lambda *_a, **_k: pytest.fail("request to a foreign host"))
    rogue = sb.Book(key="rogue", title="x", subtitle="", author="", summary="", facts=(),
                    cover_url="https://example.invalid/c.jpg", links=(), official_url="")
    with pytest.raises(sb.BookCoverError, match="official"):
        sb.fetch_cover(rogue)
    plain = sb.Book(key="rogue2", title="x", subtitle="", author="", summary="", facts=(),
                    cover_url="http://crisis2peace.org/c.jpg", links=(), official_url="")
    with pytest.raises(sb.BookCoverError, match="official"):
        sb.fetch_cover(plain)
