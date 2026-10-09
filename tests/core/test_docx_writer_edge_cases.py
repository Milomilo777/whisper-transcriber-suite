"""Edge cases for the DOCX (and other XML) writers: text lxml cannot encode.

A transcript can reach an export holding a lone surrogate (hand-edited or
pasted text, a damaged file name). lxml cannot encode one, so the whole
DOCX used to fail to save. ``sanitize_for_xml`` now replaces it with U+FFFD
and leaves every legal character, astral emoji and Persian text included,
untouched.
"""
from __future__ import annotations

import io

import pytest

from core.writers import base, docx_writer, elan

docx = pytest.importorskip("docx")

_LONE_HIGH = chr(0xD800)
_LONE_LOW = chr(0xDC80)
_REPLACEMENT = chr(0xFFFD)


def _paragraph_texts(payload: bytes) -> list[str]:
    return [p.text for p in docx.Document(io.BytesIO(payload)).paragraphs]


@pytest.mark.parametrize("surrogate", [_LONE_HIGH, _LONE_LOW])
def test_sanitize_replaces_a_lone_surrogate(surrogate):
    assert base.sanitize_for_xml(f"a{surrogate}b") == f"a{_REPLACEMENT}b"


def test_sanitize_keeps_legal_text_and_still_strips_control_characters():
    emoji = chr(0x1F600)  # one astral code point, not a surrogate pair
    persian = "سلام دنیا"
    text = f"{persian} {emoji} café"
    assert base.sanitize_for_xml(text) == text
    assert base.sanitize_for_xml("a\x00b\x0bc\x7fd") == "abcd"


def test_text_with_a_lone_surrogate_is_exported():
    segments = [{"start": 0.0, "end": 1.0, "text": f"hello{_LONE_HIGH}world"}]
    texts = _paragraph_texts(docx_writer.write_bytes(segments, "audio.mp4"))
    assert any(f"hello{_REPLACEMENT}world" in t for t in texts)


def test_speaker_with_a_lone_surrogate_is_exported():
    segments = [
        {"start": 0.0, "end": 1.0, "text": "hello", "speaker": f"Sp{_LONE_LOW}1"}
    ]
    texts = _paragraph_texts(docx_writer.write_bytes(segments, "audio.mp4"))
    assert any(f"Sp{_REPLACEMENT}1: hello" in t for t in texts)


def test_title_with_a_lone_surrogate_is_exported():
    segments = [{"start": 0.0, "end": 1.0, "text": "hello"}]
    texts = _paragraph_texts(
        docx_writer.write_bytes(segments, f"audio{_LONE_HIGH}.mp4")
    )
    assert texts[0] == f"audio{_REPLACEMENT}.mp4"


def test_persian_text_is_exported_unchanged():
    persian = "سلام دنیا"
    segments = [{"start": 0.0, "end": 1.0, "text": persian}]
    texts = _paragraph_texts(docx_writer.write_bytes(segments, "audio.mp4"))
    assert any(persian in t for t in texts)


def test_elan_output_with_a_lone_surrogate_encodes_as_utf8():
    segments = [{"start": 0.0, "end": 1.0, "text": f"hello{_LONE_HIGH}"}]
    out = elan.write(segments, "audio.mp4")
    assert f"hello{_REPLACEMENT}" in out
    out.encode("utf-8")  # raised UnicodeEncodeError before


@pytest.mark.parametrize("code", [0xFFFE, 0xFFFF])
def test_sanitize_replaces_the_two_xml_non_characters(code):
    """U+FFFE and U+FFFF are not legal XML characters (lxml: "All strings must be XML
    compatible"); they become U+FFFD like a lone surrogate."""
    assert base.sanitize_for_xml(f"a{chr(code)}b") == f"a{_REPLACEMENT}b"


@pytest.mark.parametrize("code", [0xFFFE, 0xFFFF])
def test_text_with_an_xml_non_character_is_exported(code):
    segments = [{"start": 0.0, "end": 1.0, "text": f"hello{chr(code)}world"}]
    texts = _paragraph_texts(docx_writer.write_bytes(segments, "audio.mp4"))
    assert any(f"hello{_REPLACEMENT}world" in t for t in texts)


def test_elan_output_with_an_xml_non_character_is_well_formed():
    segments = [{"start": 0.0, "end": 1.0, "text": f"hello{chr(0xFFFF)}"}]
    assert f"hello{_REPLACEMENT}" in elan.write(segments, "audio.mp4")
