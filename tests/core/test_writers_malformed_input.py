"""Malformed-segment hardening sweep across every writer.

Transcript segments reach the writers from three sources: the ASR
pipeline, ``core.convert``'s parsers, and hand-edited / externally
produced JSON re-fed for re-export (the transcript viewer loads such a
JSON verbatim and passes it straight to ``bilingual_srt`` /
``json_writer``). The viewer already coerces non-numeric timestamps
(``_seg_float``) and the TSV / JSON / ASS writers clamped some malformed
values, but the rest of the registry called ``float()`` on the raw
fields, so ONE segment with ``start=None`` / ``"abc"`` / ``Infinity`` /
a huge integer raised and dropped that entire output file while its
valid neighbours wrote fine.

Every case here fails on the pre-fix code (TypeError / ValueError /
OverflowError / AttributeError) and passes after
``core.writers.base.coerce_seconds`` + the ``normalize_text`` coercion
were applied consistently.
"""
from __future__ import annotations

import io
import json
import zipfile

import pytest

from core.writers import (
    elan,
    express_scribe,
    get_binary_writer,
    get_writer,
    inqscribe,
    json_writer,
    smtv_docx_writer,
    tsv,
    vtt,
)
from core.writers.base import (
    fmt_lrc_time,
    fmt_srt_time,
    normalize_text,
)

_TEXT_FORMATS = [
    "srt", "vtt", "tsv", "txt", "json", "lrc", "md", "otr", "elan",
    "inqscribe", "express_scribe", "ass",
]

_BINARY_FORMATS = ["docx", "pdf", "smtv_docx"]

# One malformed segment per failure mode a hand-edited / externally
# produced transcript can actually carry; the trailing segment proves the
# write did not abort before reaching valid content.
BAD_SEGMENTS = [
    {"start": None, "end": None, "text": "null times"},
    {"start": "abc", "end": "xyz", "text": "garbage times"},
    {"start": float("nan"), "end": float("inf"), "text": "nonfinite times"},
    {"start": 10 ** 400, "end": 0, "text": "huge time"},
    {"start": 3.0, "end": 4.0, "text": "missing start on the next one"},
    {"end": 4.0, "text": "no start key"},
]
GOOD_SEGMENT = {"start": 1.0, "end": 2.0, "text": "KEEP"}


def _binary_payload(fmt: str, segments: list[dict]) -> bytes:
    if fmt == "smtv_docx":
        return smtv_docx_writer.write_bytes(
            segments, "audio.wav", language="ko", work_title="audio"
        )
    return get_binary_writer(fmt)(segments, "audio.wav")


# --- malformed timestamps ---------------------------------------------------


@pytest.mark.parametrize("fmt", _TEXT_FORMATS)
def test_text_writer_survives_malformed_timestamps(fmt):
    body = get_writer(fmt)([*BAD_SEGMENTS, GOOD_SEGMENT], "audio.wav")
    assert "KEEP" in body


@pytest.mark.parametrize("fmt", _BINARY_FORMATS)
def test_binary_writer_survives_malformed_timestamps(fmt):
    payload = _binary_payload(fmt, [*BAD_SEGMENTS, GOOD_SEGMENT])
    if fmt == "pdf":
        assert payload[:5] == b"%PDF-"
    else:
        assert payload[:4] == b"PK\x03\x04"


def test_bilingual_srt_writer_survives_malformed_timestamps():
    from core.writers import bilingual_srt

    body = bilingual_srt.write(
        [*BAD_SEGMENTS, GOOD_SEGMENT], ["t"] * (len(BAD_SEGMENTS) + 1)
    )
    assert "KEEP" in body


# --- non-string text --------------------------------------------------------


@pytest.mark.parametrize("fmt", _TEXT_FORMATS)
def test_text_writer_survives_non_string_text(fmt):
    body = get_writer(fmt)([{"start": 0.0, "end": 1.0, "text": 42}], "")
    assert "42" in body


@pytest.mark.parametrize("fmt", ["docx", "smtv_docx"])
def test_docx_writer_survives_non_string_text(fmt):
    payload = _binary_payload(fmt, [{"start": 0.0, "end": 1.0, "text": 42}])
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        document_xml = zf.read("word/document.xml").decode("utf-8")
    assert "42" in document_xml


def test_pdf_writer_survives_non_string_text():
    payload = get_binary_writer("pdf")(
        [{"start": 0.0, "end": 1.0, "text": 42}], ""
    )
    assert payload[:5] == b"%PDF-"


def test_normalize_text_coerces_non_string():
    assert normalize_text(42) == "42"
    assert normalize_text(None) == ""


# --- karaoke word lists -----------------------------------------------------


def test_vtt_karaoke_falls_back_to_text_when_words_unusable():
    seg = {
        "start": 0.0,
        "end": 1.0,
        "text": "fallback words",
        "words": [{"start": None, "end": None, "word": None}],
    }
    assert "fallback words" in vtt.write([seg])


def test_vtt_karaoke_ignores_non_list_words():
    seg = {"start": 0.0, "end": 1.0, "text": "text kept", "words": 5}
    assert "text kept" in vtt.write([seg])


def test_json_writer_skips_non_dict_words():
    parsed = json.loads(json_writer.write(
        [{"start": 0.0, "end": 1.0, "text": "x", "words": ["bad", 5]}]
    ))
    assert "words" not in parsed[0]


def test_json_writer_ignores_non_list_words():
    parsed = json.loads(json_writer.write(
        [{"start": 0.0, "end": 1.0, "text": "x", "words": "nope"}]
    ))
    assert "words" not in parsed[0]


# --- shared coercion helpers ------------------------------------------------


def test_coerce_seconds_accepts_strings_and_rejects_junk():
    from core.writers.base import coerce_seconds

    assert coerce_seconds("2.5") == 2.5
    assert coerce_seconds(3) == 3.0
    assert coerce_seconds("abc") == 0.0
    assert coerce_seconds(None, 9.0) == 9.0
    assert coerce_seconds(float("nan"), 9.0) == 9.0
    assert coerce_seconds(float("inf"), 9.0) == 9.0
    assert coerce_seconds(10 ** 400) == 0.0


def test_vtt_karaoke_skips_non_dict_word_entries():
    # Sibling of test_json_writer_skips_non_dict_words: a non-dict entry
    # inside "words" used to AttributeError on w.get() and abort the file.
    seg = {
        "start": 0.0,
        "end": 2.0,
        "text": "hello world",
        "words": ["bad", 5, None, {"start": 0.0, "end": 1.0, "word": "hi"}],
    }
    body = vtt.write([seg])
    assert "hi" in body


def test_vtt_karaoke_falls_back_when_all_words_non_dict():
    seg = {
        "start": 0.0,
        "end": 1.0,
        "text": "fallback text",
        "words": ["bad", 5, None],
    }
    assert "fallback text" in vtt.write([seg])


def test_vtt_karaoke_clamps_huge_int_word_start():
    # Word-level float() caught TypeError/ValueError but not OverflowError,
    # so a huge integer word timestamp aborted the whole file.
    seg = {
        "start": 1.0,
        "end": 2.0,
        "text": "hi",
        "words": [{"start": 10 ** 400, "end": 2.0, "word": "hi"}],
    }
    assert "hi" in vtt.write([seg])


def test_ass_formatter_clamps_huge_int():
    # fmt_ass_time's bare float() raised OverflowError on integers too
    # large for a float; every sibling formatter already clamped these.
    from core.writers.ass import fmt_ass_time

    assert fmt_ass_time(10 ** 400) == "0:00:00.00"
    assert fmt_ass_time(float("inf")) == "0:00:00.00"
    assert fmt_ass_time(float("nan")) == "0:00:00.00"


def test_time_formatters_clamp_non_finite_and_huge_int():
    huge = 10 ** 400
    assert fmt_srt_time(float("inf")) == "00:00:00,000"
    assert fmt_srt_time(huge) == "00:00:00,000"
    assert fmt_lrc_time(huge) == "[00:00.00]"
    # Inf used to reach int(round(inf * 1000)) -> OverflowError.
    assert elan._ms(float("inf")) == 0
    assert elan._ms(huge) == 0
    assert inqscribe.fmt_inqscribe_time(float("inf")) == "[00:00:00.00]"
    assert inqscribe.fmt_inqscribe_time(huge) == "[00:00:00.00]"
    assert express_scribe.fmt_express_scribe_time(float("inf")) == "[00:00:00]"
    assert express_scribe.fmt_express_scribe_time(huge) == "[00:00:00]"
    assert json_writer._safe_float(huge) == 0.0
    assert tsv._ms(huge) == 0
    assert smtv_docx_writer._fmt_smtv_time(huge) == "00:00:00.0"
