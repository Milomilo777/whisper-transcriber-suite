"""About-dialog content builders are pure data — no Tk needed.

``App._show_about`` only walks the structures returned by
``build_about_sections`` / ``build_about_links`` into widgets, so the
content itself can be pinned without ever constructing a tk.Tk() root.
These tests guard that the About surface keeps advertising this
session's headline capabilities (cloud backends, Web/LAN, per-task
controls, video-wall auto-reconnect, in-place update) and that every
helpful link is a real, well-formed URL pointing at the right place.
"""
from __future__ import annotations

from urllib.parse import urlparse

import pytest

pytest.importorskip("tkinter")

from app.app import build_about_links, build_about_sections


def _all_bullet_text() -> str:
    """Flatten every bullet across every section into one lower-cased blob."""
    parts: list[str] = []
    for section_title, subsections in build_about_sections():
        parts.append(section_title)
        for sub_title, bullets in subsections:
            parts.append(sub_title)
            parts.extend(bullets)
    return "\n".join(parts).lower()


def test_sections_shape_is_well_formed():
    sections = build_about_sections()
    assert sections, "expected at least one About section"
    for section_title, subsections in sections:
        assert isinstance(section_title, str) and section_title
        assert subsections, f"section {section_title!r} has no subsections"
        for sub_title, bullets in subsections:
            assert isinstance(sub_title, str) and sub_title
            assert bullets, f"subsection {sub_title!r} has no bullets"
            for line in bullets:
                assert isinstance(line, str) and line.strip()


def test_whats_new_section_is_first():
    # The "What's new" summary should lead the dialog so a returning user
    # sees what changed without scrolling.
    sections = build_about_sections()
    assert "what's new" in sections[0][0].lower()


@pytest.mark.parametrize(
    "needle",
    [
        # Cloud backends, in plain terms.
        "gemini",
        "aistudio.google.com",
        "google cloud speech-to-text",
        "service account",
        "60 free minutes",
        "$300",
        "batch mode",
        "cloud storage bucket",
        # Local / offline backends still front and centre.
        "faster-whisper",
        "whisper.cpp",
        "parakeet",
        "transformers",
        "offline",
        # Web / LAN access.
        "web / lan access",
        "browser",
        "loopback",
        "firewall",
        "password",
        # Per-task controls.
        "pause",
        "resume",
        "re-run",
        "remove",
        # Updates.
        "check for updates",
        "upgrades in place",
    ],
)
def test_session_capabilities_are_advertised(needle: str):
    assert needle in _all_bullet_text(), f"About text is missing {needle!r}"


def test_links_are_well_formed_and_cover_the_key_destinations():
    links = build_about_links()
    assert links, "expected at least one helpful link"
    labels = [label for label, _ in links]
    urls = [url for _, url in links]

    # Every link is a (non-empty label, https URL) pair.
    for label, url in links:
        assert isinstance(label, str) and label.strip()
        assert url.startswith("https://"), url

    joined = " ".join(urls)
    assert "/releases/latest" in joined  # GitHub downloads page
    # Compare whole host names, not substrings of the URL text.
    hosts = {urlparse(url).hostname for url in urls}
    assert "aistudio.google.com" in hosts  # free Gemini key
    assert "console.cloud.google.com" in hosts  # Google Cloud console
    assert "docs/CLOUD_STT.md" in joined  # Gemini setup guide
    assert "docs/CLOUD_STT_GOOGLE.md" in joined  # Cloud STT setup guide

    # The releases link is sourced from core.updates (single source of
    # truth for the GitHub coordinates), not hand-typed.
    from core.updates import RELEASES_PAGE_URL

    assert RELEASES_PAGE_URL in urls


def test_releases_label_is_user_friendly():
    # The first link should read like a download page, not a raw URL.
    label, url = build_about_links()[0]
    assert "/releases/latest" in url
    assert "download" in label.lower() or "version" in label.lower()

def test_whats_new_lists_the_current_release_not_the_1x_highlights():
    from app.app import build_about_sections

    sections = dict(build_about_sections())
    highlights = " ".join(dict(sections["What's new in this version"])["Highlights"])
    assert "subtitled video" in highlights and "Work offline" in highlights
    assert "Per-task buttons on every queue item" not in highlights  # a 1.x highlight

def test_report_a_problem_link_points_at_this_repository_and_carries_no_paths():
    import urllib.parse

    from app.app import new_issue_url
    from core import __version__

    url = new_issue_url()
    assert url.startswith("https://github.com/Milomilo777/whisper-transcriber-suite/issues/new?")
    body = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["body"][0]
    assert f"App version: {__version__}" in body
    assert ":\\" not in body and "/Users/" not in body and "/home/" not in body
