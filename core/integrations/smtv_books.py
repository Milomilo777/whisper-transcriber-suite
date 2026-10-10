"""The two book showcases of the Supreme Master TV tab: facts and cover download.

Every fact below comes from the books' own official pages (crisis2peace.org and the
smchbooks.com product page); nothing is paraphrased beyond shortening. The tab shows
one panel per book (``app/widgets/book_panel.py``). Only the cover picture is fetched,
on a background thread, once, and kept in the user cache directory; the buttons just
open the official pages in the browser.

Cover downloads follow Work offline: a cached cover is still shown, a missing one is
refused with :class:`core.offline.OfflineModeError` and the panel draws a placeholder.
"""
from __future__ import annotations

import logging
import os
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from core import offline
from core.config import user_cache_dir

logger = logging.getLogger(__name__)

#: The only hosts a cover is ever requested from.
ALLOWED_HOSTS = frozenset({"crisis2peace.org", "smchbooks.com"})

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WhisperTranscriberSuite"
_COVER_MAX_AGE_DAYS = 30
_IMAGE_MAGIC = (b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF8", b"RIFF")  # JPEG, PNG, GIF, WebP


class BookCoverError(OSError):
    """A cover could not be fetched or was not a usable picture."""


@dataclass(frozen=True)
class BookLink:
    label: str
    url: str
    primary: bool = False


@dataclass(frozen=True)
class Book:
    key: str
    title: str
    subtitle: str
    author: str
    summary: str
    facts: tuple[str, ...]
    cover_url: str
    links: tuple[BookLink, ...]
    official_url: str


_CRISIS_PDF = ("https://crisis2peace.org/download/download_pdf.php"
               "?file=From-Crisis-to-Peace-English-S-2025-02-12.pdf")
_LOVE_PRODUCT = "https://smchbooks.com/index.php?route=product/product&product_id=1154"

BOOKS: tuple[Book, ...] = (
    Book(
        key="from-crisis-to-peace",
        title="From Crisis to Peace",
        subtitle="The Organic Vegan Way is the Answer",
        author="Supreme Master Ching Hai",
        summary=(
            "A free e-book on the organic vegan way. Its six chapters run from \"A Planetary "
            "Emergency\" and \"Warning Signs to Awaken Humanity\" through \"Organic Veganism "
            "to Heal the Planet\" to \"Humanity's Leap Into the Golden Era\"."
        ),
        facts=(
            "Free e-book",
            "Read online in 22 languages",
            "PDF in English and 13 other languages",
        ),
        cover_url="https://crisis2peace.org/img_new2/book.jpg",
        links=(
            BookLink("Read online", "https://crisis2peace.org/book.php", primary=True),
            BookLink("Download PDF", _CRISIS_PDF),
            BookLink("Learn more", "https://crisis2peace.org/"),
        ),
        official_url="https://crisis2peace.org/",
    ),
    Book(
        key="love-is-the-only-solution",
        title="Love Is The Only Solution",
        subtitle="",
        author="Supreme Master Ching Hai",
        summary=(
            "A free 90-page e-book. In its preface, Supreme Master Ching Hai says love must "
            "be shown through action: \"to be vegan, do good and protect the environment.\""
        ),
        facts=(
            "Free e-book",
            "90 pages",
            "PDF in 26 languages",
            "ISBN 978-0-578-96006-7",
        ),
        cover_url="https://smchbooks.com/image/cache/data/Love%20is%20the%20Only%20Solution-500x500.jpg",
        links=(
            BookLink("Download PDF", "https://smchbooks.com/ebook/data/english/E-LoveistheOnly.pdf",
                     primary=True),
            BookLink("Learn more", _LOVE_PRODUCT),
        ),
        official_url=_LOVE_PRODUCT,
    ),
)


def find(title: str) -> Book | None:
    """The book whose title is ``title``, or None."""
    return next((b for b in BOOKS if b.title == title), None)


def cache_dir() -> Path:
    return user_cache_dir() / "smtv_books"


def _is_official(url: str) -> bool:
    parts = urllib.parse.urlsplit(url)
    return parts.scheme == "https" and parts.hostname in ALLOWED_HOSTS


def _read_cache(path: Path) -> tuple[bytes, float] | None:
    try:
        data = path.read_bytes()
        age = time.time() - path.stat().st_mtime
    except OSError:
        return None
    return (data, age) if data else None


def _write_cache(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".part")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_bytes(data)
        os.replace(tmp, path)
    except OSError as exc:
        logger.debug("Could not cache the cover %s: %s", path, exc)
        try:
            tmp.unlink()
        except OSError:
            pass


def fetch_cover(book: Book, *, timeout: float = 15.0, limit: int = 2_000_000) -> bytes:
    """The cover picture of ``book`` (image bytes), from the cache or the official site.

    A cover younger than 30 days comes straight from the cache. An older one is
    refreshed when the network allows it and kept when it does not. While Work
    offline is on nothing is requested: a cached cover is returned, otherwise
    :class:`core.offline.OfflineModeError` is raised. Raises :class:`BookCoverError`
    for a URL off the official hosts, a reply that is not a picture or one over
    ``limit`` bytes.
    """
    if not _is_official(book.cover_url):
        raise BookCoverError(f"Cover is not on an official book site: {book.cover_url}")
    path = cache_dir() / f"{book.key}.jpg"
    cached = _read_cache(path)
    if cached and cached[1] < _COVER_MAX_AGE_DAYS * 86400:
        return cached[0]
    if offline.is_offline():
        if cached:
            return cached[0]
        raise offline.OfflineModeError(offline.refused("the book cover"))
    try:
        req = urllib.request.Request(book.cover_url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            ctype = str(resp.headers.get("Content-Type", ""))
            data = resp.read(limit + 1)
    except OSError:
        if cached:
            return cached[0]
        raise
    if len(data) > limit:
        raise BookCoverError("The cover picture is too large")
    if not ctype.startswith("image/") or not data.startswith(_IMAGE_MAGIC):
        raise BookCoverError("The cover reply is not a picture")
    _write_cache(path, data)
    return data
