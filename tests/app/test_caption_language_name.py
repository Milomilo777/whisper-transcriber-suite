"""``caption_language_name``: the display name of a yt-dlp caption code.

Covers plain codes, script and region variants, the ``-orig`` marker of
YouTube's original-language track, and codes the table does not know (shown
as they are).
"""
from __future__ import annotations

import pytest

from app.domain.languages import caption_language_name


@pytest.mark.parametrize(
    ("code", "name"),
    [
        ("es", "Spanish"),
        ("fa", "Persian"),
        ("zh-Hans", "Chinese"),
        ("zh-Hant", "Chinese"),
        ("pt-BR", "Portuguese"),
        ("fr-orig", "French"),
        ("de-orig", "German"),
    ],
)
def test_known_codes_get_their_language_name(code, name):
    assert caption_language_name(code) == name


@pytest.mark.parametrize("code", ["xx", "xx-YY", ""])
def test_unknown_codes_are_shown_as_they_are(code):
    assert caption_language_name(code) == code
