"""Tests for transcriber._normalize_language.

Regression guard for the silent no-output bug: an auto-transcribe carried
a download's "en-US" subtitle language straight into faster-whisper, which
only accepts ISO-639-1 codes and raised, so no transcript was written.
"""
from __future__ import annotations

import pytest

from core.transcriber import _normalize_language


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("en-US", "en"),    # the exact code that shipped broken
        ("pt-BR", "pt"),
        ("zh-Hans", "zh"),
        ("en_US", "en"),    # underscore variant
        ("EN", "en"),       # case-insensitive
        ("  fr  ", "fr"),   # surrounding whitespace
        ("en", "en"),
        ("fa", "fa"),
        ("yue", "yue"),     # multi-letter code kept
        # Multi-value yt-dlp subtitle codes from the language picker — these
        # crashed faster-whisper before; reduce to the base language.
        ("zh-Hans,zh-CN", "zh"),
        ("pt,pt-BR,pt-PT", "pt"),
        ("he,iw", "he"),
        ("no,nb", "no"),
        ("id,in", "id"),
    ],
)
def test_normalize_language_valid(raw, expected):
    assert _normalize_language(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        # The app's own picker table (app/domain/languages.py) ships these
        # codes; dropping them to auto-detect silently ignored the user's
        # explicit choice.
        ("iw", "he"),          # Hebrew as the picker spells it
        ("iw-Hebr", "he"),     # ... with a BCP-47 script suffix
        ("jv", "jw"),          # Javanese: Whisper uses the older "jw"
        ("in", "id"),          # deprecated Indonesian
        ("ji", "yi"),          # deprecated Yiddish
        ("nb-NO", "no"),       # Norwegian Bokmål
        ("cmn-Hans", "zh"),    # Mandarin
    ],
)
def test_normalize_language_legacy_aliases(raw, expected):
    assert _normalize_language(raw) == expected


def test_normalize_language_scans_multi_value_for_first_known_code():
    # A multi-value hint whose leading entry Whisper can't take must not
    # shadow a valid later alternative ("iw" is an alias, so it wins first).
    assert _normalize_language("xx,en") == "en"
    assert _normalize_language("iw,en") == "he"
    assert _normalize_language("xx-YY,pt-BR") == "pt"


def test_normalize_language_unknown_stays_none():
    assert _normalize_language("xx,zz") is None
    assert _normalize_language("-") is None


@pytest.mark.parametrize("raw", ["xx-BR", "und-IN", "xx-YY", "xx-BR,zz-IN"])
def test_normalize_language_ignores_region_subtags(raw):
    # "br"/"in" are Whisper languages, but here they are BCP-47 REGION
    # subtags of an unrecognised language — never promote them.
    assert _normalize_language(raw) is None


@pytest.mark.parametrize("raw", ["", None, "auto", "xx", "xx-YY", "klingon", "  "])
def test_normalize_language_falls_back_to_autodetect(raw):
    # Unknown / empty -> None so transcribe() auto-detects instead of raising.
    assert _normalize_language(raw) is None
