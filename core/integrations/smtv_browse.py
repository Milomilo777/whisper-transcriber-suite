"""Browse / search the Supreme Master TV video library.

Backs the "Supreme Master TV" tab. The site's search page
(``https://suprememastertv.com/<lang>1/search/``) renders its result list
through ``js/search.js``, which POSTs the same query string to a sibling
``loadmore`` path and injects the returned HTML fragment. We call that
endpoint directly and parse the ``<div class="sbox">`` result cards.

Stdlib only (urllib + regex), like :mod:`core.integrations.smtv`; episode
URLs returned here are exactly the ones that module already downloads.
"""
from __future__ import annotations

import html as _html
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

SITE = "https://suprememastertv.com"
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) WhisperTranscriberSuite"

#: Site languages, as listed in the site's own language menu (code, name).
LANGUAGES: tuple[tuple[str, str], ...] = (
    ("en", "English"), ("ar", "Arabic"), ("bg", "Bulgarian"),
    ("ch", "Chinese (traditional)"), ("gb", "Chinese (simplified)"), ("cs", "Czech"),
    ("de", "German"), ("es", "Spanish"), ("fa", "Persian"), ("fr", "French"),
    ("hi", "Hindi"), ("hu", "Hungarian"), ("id", "Indonesian"), ("it", "Italian"),
    ("jp", "Japanese"), ("kr", "Korean"), ("ms", "Malay"), ("mn", "Mongolian"),
    ("pl", "Polish"), ("pt", "Portuguese"), ("pa", "Punjabi"), ("ro", "Romanian"),
    ("ru", "Russian"), ("tl", "Tagalog"), ("te", "Telugu"), ("th", "Thai"),
    ("uk", "Ukrainian"), ("vn", "Vietnamese"),
)
_LANG_CODES = {code for code, _ in LANGUAGES}

#: A curated subset of the site's ~60 program filters: (label, type, category).
PROGRAMS: tuple[tuple[str, str, str], ...] = (
    ("All programs", "all", ""),
    ("Featured Programs", "featured", ""),
    ("Noteworthy News", "NWN", ""),
    ("Fly-in News", "NWN", "SMCH"),
    ("Heartline", "NWN", "HL"),
    ("Between Master and Disciples", "BMD", ""),
    ("Words of Wisdom", "WOW", ""),
    ("Veganism: The Noble Way of Living", "VEG", ""),
    ("Vegan Cooking Show", "VEG", "CS"),
    ("Animal World: Our Co-inhabitants", "AW", ""),
    ("Planet Earth: Our Loving Home", "PE", ""),
    ("Science and Spirituality", "SS", ""),
    ("Enlightening Entertainment", "EE", ""),
    ("Miracles on the Quan Yin Path", "QYP", ""),
    ("Shining World Awards", "SWA", ""),
    ("Shorts", "ADS", ""),
)


def page_url(lang: str, path: str = "") -> str:
    """Absolute site URL for ``path`` in the ``lang`` edition."""
    code = lang if lang in _LANG_CODES else "en"
    return f"{SITE}/{code}1/{path}"


LIVE_URL = f"{SITE}/webtv/"


@dataclass
class VideoItem:
    url: str
    title: str
    thumbnail: str = ""
    duration: str = ""
    abstract: str = ""
    program: str = ""
    date: str = ""
    views: int | None = None
    likes: int | None = None


@dataclass
class SearchPage:
    items: list[VideoItem] = field(default_factory=list)
    total: int | None = None
    page: int = 1

    @property
    def has_more(self) -> bool:
        if self.total is None:
            return len(self.items) >= 20
        return self.page * 20 < self.total


class SmtvBrowseError(RuntimeError):
    """The site could not be reached or returned something unexpected."""


# ---------------------------------------------------------------- fetch --


def search_url(
    lang: str = "en", query: str = "", type_: str = "all", category: str = "",
    page: int = 1,
) -> str:
    qs = urllib.parse.urlencode({
        "q": query.strip(), "type": type_ or "all", "category": category or "",
        "page": max(1, int(page)),
    })
    return page_url(lang, "search/loadmore?" + qs)


def search(
    lang: str = "en", query: str = "", type_: str = "all", category: str = "",
    page: int = 1, *, timeout: float = 30.0,
) -> SearchPage:
    """Fetch one page (20 results) of the site's search / browse listing."""
    url = search_url(lang, query, type_, category, page)
    req = urllib.request.Request(
        url, data=b"", method="POST",
        headers={"User-Agent": _UA, "X-Requested-With": "XMLHttpRequest"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 — urllib raises a wide family
        raise SmtvBrowseError(f"Could not reach Supreme Master TV: {e}") from e
    result = parse_results(body, base_url=page_url(lang, "search/"))
    result.page = max(1, int(page))
    return result


def fetch_bytes(url: str, *, timeout: float = 20.0, limit: int = 2_000_000) -> bytes:
    """Small binary GET (thumbnails). Refuses anything off the SMTV host."""
    if not re.match(r"^https://(?:www\.)?suprememastertv\.com/", url):
        raise SmtvBrowseError(f"Refusing non-SMTV URL: {url}")
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read(limit)


# ---------------------------------------------------------------- parse --

_CARD_SPLIT_RE = re.compile(r'<div class="sbox">')
_HREF_RE = re.compile(r'<h3 class="title"><a href="([^"]+)"')
_TITLE_RE = re.compile(r'<h3 class="title-program"><a[^>]*>(.*?)</a>', re.S)
_TITLE_FALLBACK_RE = re.compile(r'<h3 class="title"><a[^>]*>(.*?)</a>', re.S)
_THUMB_RE = re.compile(r'background-image:\s*url\(([^)]+)\)')
_LENGTH_RE = re.compile(r'<span class="length">([^<]*)</span>')
_ABSTRACT_RE = re.compile(r'<div class="abstract">(.*?)</div>', re.S)
_PROGRAM_RE = re.compile(
    r'<div class="types types-pc"><div class="type"><a[^>]*>(.*?)</a>', re.S
)
_DATE_RE = re.compile(r'<div class="time">\s*([0-9]{4}-[0-9]{2}-[0-9]{2})')
_VIEWS_RE = re.compile(r'id="counter-num"[^>]*>(\d+)<')
_LIKES_RE = re.compile(r'id="likenum">(\d+)<')
_NUMS_RE = re.compile(r'<div class="nums">(.*?)</div>', re.S)
_TOP_RE = re.compile(r'<span class="top">.*?</span>', re.S)


def _text(fragment: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", _TOP_RE.sub("", fragment))
    return re.sub(r"\s+", " ", _html.unescape(no_tags)).strip()


def parse_results(body: str, *, base_url: str) -> SearchPage:
    """Parse a search / loadmore HTML fragment into :class:`SearchPage`."""
    out = SearchPage()
    nums = _NUMS_RE.search(body)
    if nums:
        digits = re.findall(r"\d+", _html.unescape(nums.group(1)))
        if digits:
            out.total = int(digits[-1])
    seen: set[str] = set()
    for card in _CARD_SPLIT_RE.split(body)[1:]:
        href = _HREF_RE.search(card)
        if not href:
            continue
        url = urllib.parse.urljoin(base_url, _html.unescape(href.group(1)))
        if url in seen:
            continue
        seen.add(url)
        title_m = _TITLE_RE.search(card) or _TITLE_FALLBACK_RE.search(card)
        thumb = _THUMB_RE.search(card)
        item = VideoItem(url=url, title=_text(title_m.group(1)) if title_m else "")
        if thumb:
            item.thumbnail = urllib.parse.urljoin(
                base_url, _html.unescape(thumb.group(1).strip("'\" "))
            )
        for regex, attr in ((_LENGTH_RE, "duration"), (_PROGRAM_RE, "program"),
                            (_DATE_RE, "date")):
            m = regex.search(card)
            if m:
                setattr(item, attr, _text(m.group(1)))
        abstract = _ABSTRACT_RE.search(card)
        if abstract:
            item.abstract = _text(abstract.group(1))
        views = _VIEWS_RE.search(card)
        likes = _LIKES_RE.search(card)
        item.views = int(views.group(1)) if views else None
        item.likes = int(likes.group(1)) if likes else None
        out.items.append(item)
    return out
