"""Tests for ``app.domain.languages.subtitle_lang_args``."""
from __future__ import annotations

from app.domain.languages import (
    SUBTITLE_LANGUAGES,
    resolve_caption_kind,
    subtitle_lang_args,
)


def test_empty_string_returns_empty():
    assert subtitle_lang_args("") == ""


def test_none_returns_empty():
    assert subtitle_lang_args(None) == ""  # type: ignore[arg-type]


def test_single_code_passthrough():
    assert subtitle_lang_args("en") == "en"


def test_multi_code_preserves_order():
    assert subtitle_lang_args("zh-Hans,zh-CN") == "zh-Hans,zh-CN"


def test_strips_whitespace():
    assert subtitle_lang_args(" en , ja , ko ") == "en,ja,ko"


def test_drops_empty_segments():
    assert subtitle_lang_args("en,,ja") == "en,ja"
    assert subtitle_lang_args(",,,") == ""


def test_table_first_entry_is_automatic_with_empty_code():
    assert SUBTITLE_LANGUAGES[0] == ("Automatic", "")


def test_table_second_entry_is_english():
    assert SUBTITLE_LANGUAGES[1][0] == "English"
    assert SUBTITLE_LANGUAGES[1][1] == "en"


def test_remaining_entries_alphabetical():
    rest = SUBTITLE_LANGUAGES[2:]
    names = [name for name, _ in rest]
    assert names == sorted(names)


def test_no_duplicate_display_names():
    names = [name for name, _ in SUBTITLE_LANGUAGES]
    assert len(names) == len(set(names))


# --- resolve_caption_kind ----------------------------------------------------

def test_resolve_caption_kind_manual_match():
    assert resolve_caption_kind({"en": "manual"}, "en") == "manual"


def test_resolve_caption_kind_auto_match():
    assert resolve_caption_kind({"en": "auto"}, "en") == "auto"


def test_resolve_caption_kind_no_match():
    assert resolve_caption_kind({"de": "auto"}, "en") == ""


def test_resolve_caption_kind_empty_caption_map():
    assert resolve_caption_kind({}, "en") == ""


def test_resolve_caption_kind_multi_variant_first_hit_wins():
    # Chinese (Simplified) is stored as "zh-Hans,zh-CN"; only the second
    # code is actually present for this video.
    assert resolve_caption_kind({"zh-CN": "manual"}, "zh-Hans,zh-CN") == "manual"


def test_resolve_caption_kind_automatic_uses_fallback_lang():
    # "" is what SUBTITLE_LANGUAGES stores for "Automatic".
    assert resolve_caption_kind({"en": "auto"}, "", fallback_lang="en") == "auto"


def test_resolve_caption_kind_automatic_without_fallback():
    assert resolve_caption_kind({"en": "auto"}, "", fallback_lang="") == ""


def test_resolve_caption_kind_prefers_explicit_code_over_fallback():
    assert (
        resolve_caption_kind({"de": "manual"}, "de", fallback_lang="en") == "manual"
    )
