"""Supreme Master TV library browsing (core/integrations/smtv_browse.py).

Parses a real two-card fragment of the site's ``search/loadmore``
response (tests/fixtures/smtv_search_fragment.html) -- no network.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from core.integrations import smtv_browse as sb

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "smtv_search_fragment.html"
BASE = "https://suprememastertv.com/en1/search/"


def _page():
    return sb.parse_results(FIXTURE.read_text(encoding="utf-8"), base_url=BASE)


def test_parses_total_and_cards():
    page = _page()
    assert page.total == 1058
    assert len(page.items) == 2
    first = page.items[0]
    assert first.url.startswith("https://suprememastertv.com/en1/v/")
    assert first.url.endswith(".html")
    assert first.title.startswith("Sharing Changing Dietary Habits")
    assert first.program == "Heartline"
    assert first.date and first.date[:2] == "20" and len(first.date) == 10
    assert first.duration and ":" in first.duration
    assert first.thumbnail.startswith("https://suprememastertv.com/vimages/")
    assert first.abstract == ""  # the site leaves Heartline abstracts empty
    assert isinstance(first.views, int)


def test_episode_urls_are_ones_the_downloader_understands():
    from core.integrations.smtv import is_smtv_url, parse_episode_id

    for item in _page().items:
        assert is_smtv_url(item.url)
        assert parse_episode_id(item.url) is not None


def test_top_badge_is_not_part_of_the_title():
    html = ('<div class="nums">1 - 1 of 1 Results</div><div class="sbox">'
            '<h3 class="title"><a href="../../en1/v/123456789.html">'
            '<span class="top">TOP</span>Hello &amp; welcome</a></h3></div>')
    page = sb.parse_results(html, base_url=BASE)
    assert page.items[0].title == "Hello & welcome"
    assert page.total == 1


def test_abstract_is_unwrapped_and_unescaped():
    html = ('<div class="sbox"><h3 class="title"><a href="../../en1/v/1.html">T</a></h3>'
            '<div class="abstract"><a href="x">Kind &amp;\n  gentle   words</a></div></div>')
    assert sb.parse_results(html, base_url=BASE).items[0].abstract == "Kind & gentle words"


def test_empty_or_garbage_response():
    page = sb.parse_results("<html>nothing here</html>", base_url=BASE)
    assert page.items == [] and page.total is None


@pytest.mark.parametrize("total,page,expected", [
    (1058, 1, True), (40, 2, False), (41, 2, True), (None, 1, False),
])
def test_has_more(total, page, expected):
    assert sb.SearchPage(items=[], total=total, page=page).has_more is expected


def test_search_url_and_language_fallback():
    url = sb.search_url("fa", " vegan ", "NWN", "HL", 3)
    parsed = urlparse(url)
    assert parsed.path == "/fa1/search/loadmore"
    assert parse_qs(parsed.query) == {
        "q": ["vegan"], "type": ["NWN"], "category": ["HL"], "page": ["3"]
    }
    assert sb.page_url("xx", "about-us/") == "https://suprememastertv.com/en1/about-us/"


def test_fetch_bytes_refuses_other_hosts():
    with pytest.raises(sb.SmtvBrowseError):
        sb.fetch_bytes("https://example.com/evil.jpg")


def test_search_wraps_network_errors(monkeypatch):
    def boom(*a, **kw):
        raise OSError("offline")

    monkeypatch.setattr(sb.urllib.request, "urlopen", boom)
    with pytest.raises(sb.SmtvBrowseError):
        sb.search("en")
