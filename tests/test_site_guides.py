"""Guide pages under site/<slug>/index.html stay findable and self-consistent.

Every guide must be listed in the sitemap and in llms.txt, linked from the home
page, carry a canonical URL for its own slug, a unique title, one h1, valid
JSON-LD, and no version number (release facts go stale; only the home page is
refreshed by tools/update_site_data.py).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
BASE = "https://whisper-transcriber-suite.pages.dev/"
GUIDES = sorted(p.parent.name for p in SITE.glob("*/index.html"))


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _one(pattern: str, text: str) -> str:
    m = re.search(pattern, text)
    assert m, f"missing: {pattern}"
    return m.group(1)


def test_guides_exist():
    assert GUIDES, "no guide pages found under site/<slug>/index.html"


@pytest.mark.parametrize("slug", GUIDES)
def test_guide_is_listed_and_linked(slug):
    url = f"{BASE}{slug}/"
    assert f"<loc>{url}</loc>" in _read(SITE / "sitemap.xml"), f"{slug} missing from sitemap.xml"
    assert url in _read(SITE / "llms.txt"), f"{slug} missing from llms.txt"
    assert f'href="/{slug}/"' in _read(SITE / "index.html"), f"home page does not link /{slug}/"


@pytest.mark.parametrize("slug", GUIDES)
def test_guide_head_and_body(slug):
    html = _read(SITE / slug / "index.html")
    assert f'<link rel="canonical" href="{BASE}{slug}/">' in html
    assert len(re.findall(r"<h1[\s>]", html)) == 1
    title = _one(r"<title>(.*?)</title>", html)
    assert len(title) <= 65, title
    desc = _one(r'<meta name="description" content="(.*?)"', html)
    assert len(desc) <= 160, desc
    for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S):
        json.loads(block)
    text = re.sub(r"<(script|style)[\s\S]*?</\1>|<[^>]+>", " ", html)
    assert not re.search(r"\bv?\d+\.\d+\.\d+\b", text), "visible version number goes stale"


def test_guide_titles_are_unique():
    titles = [_one(r"<title>(.*?)</title>", _read(SITE / s / "index.html")) for s in GUIDES]
    assert len(set(titles)) == len(titles)
