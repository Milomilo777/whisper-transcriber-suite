"""A lone surrogate in a transcript must not cost any export format.

Text can reach the writers holding one half of a surrogate pair (a hand-edited or damaged
JSON, a file name Python could not decode). ``str.encode("utf-8")`` refuses it, so every
text writer's output failed to save and the format was skipped with a log warning. The
shared text helpers now replace each lone half with U+FFFD, so the file is written and the
rest of the text survives.
"""
from __future__ import annotations

import json

import pytest

from core import writers
from core.writers import base, bilingual_srt

_HIGH = chr(0xD800)
_LOW = chr(0xDC80)
_REPLACEMENT = chr(0xFFFD)

# Every field a writer reads text from, each with its own lone half.
_SEGMENTS = [
    {
        "start": 0.0,
        "end": 1.5,
        "text": f"hello{_HIGH}world",
        "speaker": f"Sp{_LOW}1",
        "words": [
            {"start": 0.0, "end": 0.7, "word": f"hello{_HIGH}", "probability": 0.9},
            {"start": 0.7, "end": 1.5, "word": "world", "probability": 0.9},
        ],
        "suspect": True,
        "suspect_reason": f"odd{_LOW}",
    },
    {"start": 1.5, "end": 3.0, "text": "plain second line"},
]
_AUDIO = f"clip{_HIGH}.mp3"


@pytest.mark.parametrize("name", sorted(writers.WRITERS))
def test_every_text_writer_output_encodes_as_utf8(name):
    body = writers.get_writer(name)(_SEGMENTS, _AUDIO)
    body.encode("utf-8")  # raised UnicodeEncodeError before
    assert "plain second line" in body, "the rest of the transcript must survive"


@pytest.mark.parametrize(
    "name", [n for n in sorted(writers.WRITERS) if n not in ("json", "express_scribe", "otr")]
)
def test_the_text_keeps_its_place_with_a_replacement_character(name):
    body = writers.get_writer(name)(_SEGMENTS, _AUDIO)
    assert f"hello{_REPLACEMENT}world" in body or f"hello{_REPLACEMENT}" in body


def test_json_text_and_labels_are_replaced():
    data = json.loads(writers.get_writer("json")(_SEGMENTS, _AUDIO))
    assert data[0]["text"] == f"hello{_REPLACEMENT}world"
    assert data[0]["speaker"] == f"Sp{_REPLACEMENT}1"
    assert data[0]["suspect_reason"] == f"odd{_REPLACEMENT}"
    assert data[0]["words"][0]["word"] == f"hello{_REPLACEMENT}"
    assert _HIGH not in writers.get_writer("json")(_SEGMENTS, _AUDIO)


@pytest.mark.parametrize("name", ["docx", "pdf"])
def test_binary_writers_still_export(name):
    payload = writers.get_binary_writer(name)(_SEGMENTS, _AUDIO)
    assert payload[:2] in (b"PK", b"%P")


def test_bilingual_srt_encodes_as_utf8():
    out = bilingual_srt.write(_SEGMENTS, [f"tr{_HIGH}", "second"], _AUDIO)
    out.encode("utf-8")
    assert f"hello{_REPLACEMENT}world" in out


def test_normalize_text_replaces_each_lone_half_and_keeps_pairs_of_astral_text():
    astral = chr(0x1F600)  # one code point in a Python str, never two halves
    assert base.normalize_text(f"a  {_HIGH}\t{_LOW}b {astral}") == (
        f"a {_REPLACEMENT} {_REPLACEMENT}b {astral}"
    )
    assert base.normalize_text("سلام  دنیا") == "سلام دنیا"

def test_elan_media_url_survives_a_name_the_system_cannot_encode(monkeypatch):
    # POSIX file systems cannot encode a lone surrogate; resolve() raises there.
    from core.writers import elan

    def refuse(self, strict=False):
        raise UnicodeEncodeError("utf-8", "x", 0, 1, "surrogates not allowed")

    monkeypatch.setattr(elan.Path, "resolve", refuse)
    url = elan._media_url(_AUDIO)
    assert url.startswith("file:") and "clip" in url
