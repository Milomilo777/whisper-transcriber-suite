"""OTR's decoded literal text must never be parsed as SubRip syntax."""
from __future__ import annotations

import html
import json

import pytest

from core import convert
from core.writers import WRITERS


@pytest.mark.parametrize("text", [
    "Type <b>bold</b> literally",
    "<i>",
    "Use <br> here",
    "00:00:05,000 --> 00:00:06,000",
])
def test_writer_roundtrip_preserves_literal_otr_text(tmp_path, text):
    segments = [{"start": 1.0, "end": 2.0, "text": text},
                {"start": 4.0, "end": 5.0, "text": "The next cue survives"}]
    source = tmp_path / "transcript.otr"
    body = WRITERS["otr"](segments, "clip.wav")
    source.write_text(body, encoding="utf-8")
    result = convert.parse_to_segments(str(source))
    assert [segment["text"] for segment in result] == [text, "The next cue survives"]
    assert [segment["start"] for segment in result] == [1.0, 4.0]
    assert source.read_text(encoding="utf-8") == body


def test_real_otr_markup_is_styling_but_escaped_markup_is_literal(tmp_path):
    source = tmp_path / "external.otr"
    source.write_text(json.dumps({"text":
        '<p><span class="timestamp" data-timestamp="2">00:02</span>'
        '<b>Bold words</b> and ' + html.escape('<i>literal tags</i>') + '</p>',
        "media-time": 10}), encoding="utf-8")
    assert convert.parse_to_segments(str(source)) == [
        {"start": 2.0, "end": 10.0, "text": "Bold words and <i>literal tags</i>"}]


def test_plain_import_keeps_existing_end_time_inference(tmp_path):
    source = tmp_path / "plain.otr"
    source.write_text(WRITERS["otr"]([
        {"start": 1.0, "end": 2.0, "text": "First cue"},
        {"start": 4.0, "end": 6.0, "text": "Second cue"}], "clip.wav"), encoding="utf-8")
    assert convert.parse_to_segments(str(source)) == [
        {"start": 1.0, "end": 4.0, "text": "First cue"},
        {"start": 4.0, "end": 9.0, "text": "Second cue"}]


@pytest.mark.parametrize("start,expected_start,expected_end", [
    (1.23456, 1.235, 10.0), (-1.0, 0.0, 10.0), (1e308, 0.0, 0.0),
])
def test_direct_import_keeps_existing_clock_coercion(tmp_path, start, expected_start, expected_end):
    source = tmp_path / "clock.otr"
    source.write_text(json.dumps({"text":
        f'<p><span class="timestamp" data-timestamp="{start}">timestamp</span>Words</p>',
        "media-time": 10}), encoding="utf-8")
    assert convert.parse_to_segments(str(source)) == [
        {"start": expected_start, "end": expected_end, "text": "Words"}]


@pytest.mark.parametrize("format_name,extension", [
    ("json", "json"), ("vtt", "vtt"), ("ass", "ass"),
    ("tsv", "tsv"), ("elan", "eaf"), ("inqscribe", "inqscr"),
])
def test_real_conversion_keeps_every_cue_and_prior_files(tmp_path, format_name, extension):
    texts = ["<i>", "00:00:05,000 --> 00:00:06,000", "Type <b>bold</b> literally"]
    source = tmp_path / "transcript.otr"
    body = WRITERS["otr"]([
        {"start": float(i * 3), "end": float(i * 3 + 1), "text": text}
        for i, text in enumerate(texts)], "clip.wav")
    source.write_text(body, encoding="utf-8")
    prior = source.with_suffix("." + extension)
    prior.write_bytes(b"previous edited transcript")
    output = convert.convert_file(str(source), format_name)
    assert [segment["text"] for segment in convert.parse_to_segments(output)] == texts
    assert prior.read_bytes() == b"previous edited transcript"
    assert source.read_text(encoding="utf-8") == body
