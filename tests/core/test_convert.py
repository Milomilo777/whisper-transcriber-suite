"""Tests for ``core.convert`` — transcript format conversion.

Round-trips SRT / VTT / TSV / JSON into the universal segment list and back
out via the writers registry, plus the .otr import and graceful handling of
bad / empty / output-only (.txt) input.
"""
from __future__ import annotations

import json

import pytest

from core import convert
from core.integrations import otranscribe


# --- parse round-trips ------------------------------------------------------

SRT_SAMPLE = (
    "1\n"
    "00:00:01,000 --> 00:00:03,500\n"
    "Hello world\n"
    "\n"
    "2\n"
    "00:00:03,500 --> 00:00:06,000\n"
    "Second line\n"
)

VTT_SAMPLE = (
    "WEBVTT\n"
    "\n"
    "00:00:01.000 --> 00:00:03.500\n"
    "Hello world\n"
    "\n"
    "00:00:03.500 --> 00:00:06.000\n"
    "Second line\n"
)

TSV_SAMPLE = (
    "start\tend\ttext\n"
    "1000\t3500\tHello world\n"
    "3500\t6000\tSecond line\n"
)

JSON_SAMPLE = json.dumps(
    [
        {"start": 1.0, "end": 3.5, "text": "Hello world"},
        {"start": 3.5, "end": 6.0, "text": "Second line"},
    ]
)


@pytest.mark.parametrize(
    "ext,content",
    [
        ("srt", SRT_SAMPLE),
        ("vtt", VTT_SAMPLE),
        ("tsv", TSV_SAMPLE),
        ("json", JSON_SAMPLE),
    ],
)
def test_parse_to_segments_structure(tmp_path, ext, content):
    p = tmp_path / f"sample.{ext}"
    p.write_text(content, encoding="utf-8")
    segs = convert.parse_to_segments(str(p))
    assert len(segs) == 2
    assert segs[0]["start"] == pytest.approx(1.0)
    assert segs[0]["end"] == pytest.approx(3.5)
    assert segs[0]["text"] == "Hello world"
    assert segs[1]["text"] == "Second line"
    assert segs[1]["end"] == pytest.approx(6.0)


@pytest.mark.parametrize("ext,content", [
    ("srt", SRT_SAMPLE), ("vtt", VTT_SAMPLE),
    ("tsv", TSV_SAMPLE), ("json", JSON_SAMPLE),
])
def test_convert_to_srt(tmp_path, ext, content):
    p = tmp_path / f"sample.{ext}"
    p.write_text(content, encoding="utf-8")
    out = convert.convert_file(str(p), "srt")
    assert out.endswith(".srt")
    body = open(out, encoding="utf-8").read()
    assert "Hello world" in body
    assert "00:00:01,000 --> 00:00:03,500" in body
    # Re-parsing the emitted SRT yields the same two segments.
    assert len(convert.parse_to_segments(out)) == 2


@pytest.mark.parametrize("ext,content", [
    ("srt", SRT_SAMPLE), ("vtt", VTT_SAMPLE),
    ("tsv", TSV_SAMPLE), ("json", JSON_SAMPLE),
])
def test_convert_to_json(tmp_path, ext, content):
    p = tmp_path / f"sample.{ext}"
    p.write_text(content, encoding="utf-8")
    out = convert.convert_file(str(p), "json")
    data = json.loads(open(out, encoding="utf-8").read())
    assert isinstance(data, list)
    assert len(data) == 2
    assert data[0]["text"] == "Hello world"
    assert data[0]["start"] == pytest.approx(1.0)


def test_convert_same_format_does_not_clobber_source(tmp_path):
    p = tmp_path / "sample.srt"
    p.write_text(SRT_SAMPLE, encoding="utf-8")
    out = convert.convert_file(str(p), "srt")
    # In-place re-emit must NOT overwrite the source.
    assert out != str(p)
    assert ".converted" in out
    assert p.read_text(encoding="utf-8") == SRT_SAMPLE


def test_otr_is_a_convert_target():
    assert "otr" in convert.CONVERT_TARGETS


def test_output_extension_for_matches_default_out_path():
    """The UI format picker (app.app._ask_convert_format) shows this next to
    each format name so users can tell what file they'll actually get; it
    must agree with what convert_file() really writes."""
    for fmt in convert.CONVERT_TARGETS:
        ext = convert.output_extension_for(fmt)
        assert convert._default_out_path("x", fmt) == f"x.{ext}"
    # The exceptions where the registry key differs from the extension.
    assert convert.output_extension_for("elan") == "eaf"
    assert convert.output_extension_for("inqscribe") == "inqscr"
    assert convert.output_extension_for("express_scribe") == "txt"
    assert convert.output_extension_for("smtv_docx") == "docx"
    # Most formats: the key already IS the extension.
    assert convert.output_extension_for("srt") == "srt"
    assert convert.output_extension_for("OTR") == "otr"  # case-insensitive


@pytest.mark.parametrize("ext,content", [
    ("srt", SRT_SAMPLE), ("vtt", VTT_SAMPLE),
    ("tsv", TSV_SAMPLE), ("json", JSON_SAMPLE),
])
def test_convert_to_otr(tmp_path, ext, content):
    p = tmp_path / f"sample.{ext}"
    p.write_text(content, encoding="utf-8")
    out = convert.convert_file(str(p), "otr")
    assert out.endswith(".otr")
    payload = json.loads(open(out, encoding="utf-8").read())
    assert set(payload.keys()) == {"text", "media", "media-source", "media-time"}
    assert "Hello world" in payload["text"]
    # Re-parsing the emitted .otr recovers both segments.
    assert len(convert.parse_to_segments(out)) == 2


def test_explicit_out_path(tmp_path):
    p = tmp_path / "sample.json"
    p.write_text(JSON_SAMPLE, encoding="utf-8")
    target = tmp_path / "out" / "result.vtt"
    out = convert.convert_file(str(p), "vtt", str(target))
    assert out == str(target)
    body = target.read_text(encoding="utf-8")
    assert body.startswith("WEBVTT")


# --- .otr import ------------------------------------------------------------

def test_otr_import(tmp_path):
    # Build an .otr from a known SRT via the existing helper, then parse it.
    srt = tmp_path / "src.srt"
    srt.write_text(SRT_SAMPLE, encoding="utf-8")
    otr_text = otranscribe.srt_to_otr(str(srt), media_filename="src.mp4")
    otr = tmp_path / "src.otr"
    otr.write_text(otr_text, encoding="utf-8")

    segs = convert.parse_to_segments(str(otr))
    assert len(segs) == 2
    assert segs[0]["text"] == "Hello world"
    # .otr -> srt convert works end to end.
    out = convert.convert_file(str(otr), "srt")
    assert "Hello world" in open(out, encoding="utf-8").read()


# --- bad / empty / output-only input ----------------------------------------

def test_txt_is_output_only(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_text("just some text\nno timestamps\n", encoding="utf-8")
    with pytest.raises(convert.ConvertError):
        convert.parse_to_segments(str(p))


def test_missing_file(tmp_path):
    with pytest.raises(convert.ConvertError):
        convert.parse_to_segments(str(tmp_path / "nope.srt"))


def test_empty_file(tmp_path):
    p = tmp_path / "empty.srt"
    p.write_text("", encoding="utf-8")
    # An empty SRT is a valid-but-cue-less file: zero segments, no crash.
    assert convert.parse_to_segments(str(p)) == []


def test_empty_unknown_extension_raises(tmp_path):
    p = tmp_path / "empty.dat"
    p.write_text("", encoding="utf-8")
    with pytest.raises(convert.ConvertError):
        convert.parse_to_segments(str(p))


def test_bad_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json", encoding="utf-8")
    with pytest.raises(convert.ConvertError):
        convert.parse_to_segments(str(p))


def test_unknown_output_format(tmp_path):
    p = tmp_path / "sample.srt"
    p.write_text(SRT_SAMPLE, encoding="utf-8")
    with pytest.raises(convert.ConvertError):
        convert.convert_file(str(p), "docx")  # binary writer, not offered
    with pytest.raises(convert.ConvertError):
        convert.convert_file(str(p), "bogus")


def test_content_sniff_no_extension(tmp_path):
    # No / unknown extension: detect by content.
    p = tmp_path / "noext"
    p.write_text(SRT_SAMPLE, encoding="utf-8")
    segs = convert.parse_to_segments(str(p))
    assert len(segs) == 2


# --- dedupe_rolling_captions -------------------------------------------------

def test_dedupe_rolling_captions_strips_overlap():
    # Mirrors YouTube's rolling auto-caption shape: each cue repeats the
    # previous cue's tail before adding new words.
    segments = [
        {"start": 0.0, "end": 4.0, "text": "Hello everyone welcome to the show"},
        {"start": 3.5, "end": 7.0, "text": "to the show today we will talk"},
        {"start": 6.5, "end": 10.0, "text": "today we will talk about testing"},
    ]
    cleaned = convert.dedupe_rolling_captions(segments)
    assert [s["text"] for s in cleaned] == [
        "Hello everyone welcome to the show",
        "today we will talk",
        "about testing",
    ]
    # Timing is preserved from the original (untrimmed) cue.
    assert [s["start"] for s in cleaned] == [0.0, 3.5, 6.5]


def test_dedupe_rolling_captions_drops_fully_repeated_cue():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "one two three"},
        {"start": 1.5, "end": 2.2, "text": "two three"},
    ]
    cleaned = convert.dedupe_rolling_captions(segments)
    assert [s["text"] for s in cleaned] == ["one two three"]


def test_dedupe_rolling_captions_is_case_insensitive():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hello There"},
        {"start": 1.5, "end": 3.0, "text": "hello there general kenobi"},
    ]
    cleaned = convert.dedupe_rolling_captions(segments)
    assert [s["text"] for s in cleaned] == ["Hello There", "general kenobi"]


def test_dedupe_rolling_captions_noop_on_ordinary_subtitles():
    # No cross-cue word overlap -- a normal manually-authored subtitle must
    # pass through completely unchanged.
    segments = [
        {"start": 0.0, "end": 2.0, "text": "I think that's right."},
        {"start": 2.0, "end": 4.0, "text": "Let's move on to the next topic."},
    ]
    cleaned = convert.dedupe_rolling_captions(segments)
    assert cleaned == segments


def test_dedupe_rolling_captions_empty_input():
    assert convert.dedupe_rolling_captions([]) == []


# --- convert_file(segments=...) ----------------------------------------------

def test_convert_file_accepts_preparsed_segments(tmp_path):
    # A caller that already parsed (and possibly de-duplicated) the
    # segments must be able to skip re-parsing in_path.
    p = tmp_path / "sample.vtt"
    p.write_text(VTT_SAMPLE, encoding="utf-8")
    override = [{"start": 0.0, "end": 1.0, "text": "Overridden text"}]
    out = convert.convert_file(str(p), "txt", segments=override)
    assert "Overridden text" in open(out, encoding="utf-8").read()
    assert "Hello world" not in open(out, encoding="utf-8").read()


# --- hand-edited JSON malformed fields ---------------------------------------


def test_parse_json_coerces_non_string_text(tmp_path):
    # (value or "").strip() used to raise AttributeError (not ConvertError)
    # on a numeric text field, crashing the whole conversion.
    p = tmp_path / "numeric_text.json"
    p.write_text('[{"start": 0.0, "end": 1.0, "text": 42}]', encoding="utf-8")
    segs = convert.parse_to_segments(str(p))
    assert segs[0]["text"] == "42"


def test_parse_json_tolerates_huge_integer_timestamps(tmp_path):
    # float(10**400) raises OverflowError, which the old handler did not
    # catch.
    p = tmp_path / "huge.json"
    p.write_text(
        '[{"start": %d, "end": 1.0, "text": "hi"}]' % (10 ** 400),
        encoding="utf-8",
    )
    segs = convert.parse_to_segments(str(p))
    assert segs[0]["start"] == 0.0
    assert segs[0]["end"] == 1.0


def test_convert_file_survives_hand_edited_json(tmp_path):
    payload = [
        {"start": None, "end": None, "text": "null times"},
        {"start": "abc", "end": "xyz", "text": "garbage times"},
        {"start": 0.5, "end": 1.0, "text": 42},
        {"start": 1.0, "end": 2.0, "text": "kept"},
    ]
    src = tmp_path / "hand.json"
    src.write_text(json.dumps(payload), encoding="utf-8")
    out = convert.convert_file(str(src), "srt")
    body = open(out, encoding="utf-8").read()
    assert "kept" in body
    assert "42" in body
    # Every segment made it into the output (nothing was skipped).
    assert len(convert.parse_to_segments(out)) == len(payload)
