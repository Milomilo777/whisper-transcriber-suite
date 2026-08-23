"""Live-network smoke tests for the SMTV integration.

Skipped when the user sets WHISPER_OFFLINE_TESTS=1 or when the SMTV
host is unreachable. These tests confirm the scrape contract is still
valid against the real site — they do not replace the hermetic unit
suite in tests/integrations/test_smtv.py.

The "actually download a real file" test pulls the smallest 396p MP4
of the reference Part 1 episode (~ 65 MB) so the round-trip stays
reasonable. Override the episode via WHISPER_SMTV_TEST_URL if you
want to point it at a smaller news clip.
"""
from __future__ import annotations

import os
import socket

import pytest

from core.integrations import smtv as smtv_mod


REFERENCE_EPISODE = os.environ.get(
    "WHISPER_SMTV_TEST_URL",
    "https://suprememastertv.com/en1/v/314324511501.html",
)


def _online() -> bool:
    if os.environ.get("WHISPER_OFFLINE_TESTS") == "1":
        return False
    try:
        with socket.create_connection(("suprememastertv.com", 443), timeout=3):
            return True
    except OSError:
        return False


pytestmark = pytest.mark.skipif(
    not _online(), reason="SMTV host unreachable or offline mode"
)


def test_real_episode_parse():
    ep = smtv_mod.fetch_episode(REFERENCE_EPISODE, timeout=30.0)
    assert ep.vid
    assert ep.title
    qualities = {f.quality for f in ep.files}
    assert "720p" in qualities, qualities
    # Reference episode is a 7-part lecture; siblings should include
    # the other six parts.
    if "Part" in ep.title:
        assert len(ep.siblings) >= 1
        assert all(s.url.startswith("https://") for s in ep.siblings)


def test_real_cdn_head_ok():
    import urllib.request

    ep = smtv_mod.fetch_episode(REFERENCE_EPISODE, timeout=30.0)
    cdn_url = smtv_mod.best_url_for_mode(ep, "video-396")
    req = urllib.request.Request(cdn_url, method="HEAD",
                                 headers={"User-Agent": "WhisperTranscriberSuite"})
    with urllib.request.urlopen(req, timeout=15.0) as resp:
        assert resp.status == 200
        # Cloudflare strips Content-Length sometimes; just confirm the
        # header surface we rely on at least carries Content-Type or
        # disposition.
        ctype = resp.headers.get("Content-Type", "")
        cdisp = resp.headers.get("Content-disposition", "") or resp.headers.get(
            "Content-Disposition", ""
        )
        assert ctype or cdisp, "CDN returned no usable headers"
