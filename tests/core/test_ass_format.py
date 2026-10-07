"""Tests for the ASS/SSA writer and parser.

ASS is what video editors, karaoke tools and libass consume, so the
output has to be structurally correct — a subtly wrong timestamp or an
unescaped brace makes a player drop the line silently rather than
complain.
"""
from __future__ import annotations

import pytest

from core import convert
from core.writers import WRITERS, ass, get_writer, supported_formats


SEGMENTS = [
    {
        "start": 1.0, "end": 3.5, "text": "Hello world", "speaker": "SPEAKER_00",
        "words": [
            {"word": "Hello", "start": 1.0, "end": 1.6},
            {"word": "world", "start": 1.8, "end": 3.5},
        ],
    },
    {"start": 4.0, "end": 5.25, "text": "Second cue, with a comma"},
]


# ------------------------------------------------------------- registration


def test_ass_is_a_registered_writer():
    assert "ass" in WRITERS
    assert "ass" in supported_formats()


def test_ass_is_a_parseable_input_format():
    assert "ass" in convert.PARSE_FORMATS


def test_ass_is_offered_as_a_conversion_target():
    assert "ass" in convert.CONVERT_TARGETS
    assert convert.output_extension_for("ass") == "ass"


# ------------------------------------------------------------- timestamps


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.0, "0:00:00.00"),
        (1.0, "0:00:01.00"),
        (61.5, "0:01:01.50"),
        (3661.25, "1:01:01.25"),
        (59.996, "0:01:00.00"),      # carry, never "0:00:60.00"
        (-5.0, "0:00:00.00"),        # negative clamps
        (float("nan"), "0:00:00.00"),
        (float("inf"), "0:00:00.00"),
        (None, "0:00:00.00"),
    ],
)
def test_ass_timestamp_formatting(seconds, expected):
    assert ass.fmt_ass_time(seconds) == expected


def test_ass_uses_a_single_hour_digit_and_centiseconds():
    """SRT's 'HH:MM:SS,mmm' here makes players mis-time or drop the line."""
    stamp = ass.fmt_ass_time(1.0)
    hours, _, rest = stamp.partition(":")
    assert len(hours) == 1
    assert "," not in stamp
    assert len(rest.split(".")[-1]) == 2


def test_hours_beyond_nine_are_written_in_full():
    # libass, ffmpeg and Aegisub read the hour as an integer of any width;
    # clamping to 9 put every cue past ten hours at the wrong time.
    assert ass.fmt_ass_time(11 * 3600) == "11:00:00.00"


# ---------------------------------------------------------------- escaping


def test_braces_are_escaped():
    """An unescaped '{' opens an override block and eats the rest."""
    out = ass.escape_ass_text("a {styled} word")
    assert "\\{" in out and "\\}" in out


def test_newlines_become_the_ass_line_break():
    assert ass.escape_ass_text("one\ntwo") == "one\\Ntwo"
    assert ass.escape_ass_text("one\r\ntwo") == "one\\Ntwo"


def test_backslashes_are_escaped():
    assert ass.escape_ass_text("a\\b") == "a\\\\b"


def test_escaping_empty_input():
    assert ass.escape_ass_text("") == ""
    assert ass.escape_ass_text(None) == ""  # type: ignore[arg-type]


# ------------------------------------------------------------------ writing


def test_script_has_the_three_required_sections():
    out = get_writer("ass")(SEGMENTS, "audio.wav")
    assert "[Script Info]" in out
    assert "[V4+ Styles]" in out
    assert "[Events]" in out
    assert "ScriptType: v4.00+" in out


def test_events_section_declares_its_column_order():
    out = get_writer("ass")(SEGMENTS, "")
    events = out.split("[Events]", 1)[1]
    assert events.lstrip().startswith("Format:")


def test_each_segment_becomes_one_dialogue_line():
    out = get_writer("ass")(SEGMENTS, "")
    assert len([ln for ln in out.splitlines() if ln.startswith("Dialogue:")]) == 2


def test_speaker_goes_in_the_name_field_not_the_text():
    """ASS has an actor column; prefixing the text would make every
    downstream tool parse the label back out of the subtitle."""
    out = get_writer("ass")(SEGMENTS, "")
    line = [ln for ln in out.splitlines() if ln.startswith("Dialogue:")][0]
    fields = line.split(",", 9)
    assert fields[4] == "SPEAKER_00"
    assert "SPEAKER_00:" not in fields[9]


def test_a_comma_in_a_speaker_label_cannot_shift_the_fields():
    out = get_writer("ass")([{"start": 0, "end": 1, "text": "x",
                             "speaker": "Smith, John"}], "")
    line = [ln for ln in out.splitlines() if ln.startswith("Dialogue:")][0]
    assert len(line.split(",", 9)) == 10
    assert "Smith; John" in line


def test_commas_in_the_text_survive():
    """Text is the last field, so its commas are literal."""
    out = get_writer("ass")(SEGMENTS, "")
    assert "Second cue, with a comma" in out


def test_word_timings_become_karaoke_tags():
    """The point of ASS here: word-level data previously only reached VTT."""
    out = get_writer("ass")(SEGMENTS, "")
    line = [ln for ln in out.splitlines() if ln.startswith("Dialogue:")][0]
    assert "{\\k" in line
    assert line.count("{\\k") == 2


def test_karaoke_durations_are_relative_centiseconds():
    """'Hello' 1.0-1.6s = 60cs; 'world' 1.6-3.5s incl. the 0.2s pause = 190cs."""
    out = get_writer("ass")(SEGMENTS, "")
    line = [ln for ln in out.splitlines() if ln.startswith("Dialogue:")][0]
    assert "{\\k60}Hello" in line
    assert "{\\k190}world" in line


def test_karaoke_durations_sum_to_the_cue_length():
    """Otherwise the highlight drifts away from the voice."""
    import re

    seg = SEGMENTS[0]
    out = get_writer("ass")([seg], "")
    line = [ln for ln in out.splitlines() if ln.startswith("Dialogue:")][0]
    total_cs = sum(int(v) for v in re.findall(r"\{\\k(\d+)\}", line))
    expected = int(round((seg["end"] - seg["start"]) * 100))
    assert abs(total_cs - expected) <= 1


def test_segment_without_words_writes_plain_text():
    out = get_writer("ass")([{"start": 0, "end": 1, "text": "plain"}], "")
    line = [ln for ln in out.splitlines() if ln.startswith("Dialogue:")][0]
    assert line.endswith("plain")
    assert "{\\k" not in line


def test_empty_and_malformed_input_do_not_raise():
    assert "[Events]" in get_writer("ass")([], "")
    out = get_writer("ass")(
        [{"start": "bad", "end": None, "text": "kept"},
         "not a dict",  # type: ignore[list-item]
         {"start": 5, "end": 1, "text": "reversed"}],
        "",
    )
    assert "kept" in out and "reversed" in out


def test_blank_segments_are_skipped():
    out = get_writer("ass")([{"start": 0, "end": 1, "text": "   "}], "")
    assert not [ln for ln in out.splitlines() if ln.startswith("Dialogue:")]


# ------------------------------------------------------------------ parsing


def _write(tmp_path, name, body):
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_round_trip_preserves_timings_text_and_speaker(tmp_path):
    path = _write(tmp_path, "t.ass", get_writer("ass")(SEGMENTS, ""))
    back = convert.parse_to_segments(path)
    assert len(back) == 2
    assert back[0]["start"] == pytest.approx(1.0)
    assert back[0]["end"] == pytest.approx(3.5)
    assert back[0]["speaker"] == "SPEAKER_00"
    assert back[0]["text"] == "Hello world"
    assert back[1]["text"] == "Second cue, with a comma"


def test_karaoke_tags_are_stripped_on_parse(tmp_path):
    path = _write(tmp_path, "t.ass", get_writer("ass")(SEGMENTS, ""))
    back = convert.parse_to_segments(path)
    assert "\\k" not in back[0]["text"]
    assert "{" not in back[0]["text"]


def test_parses_legacy_ssa_column_order(tmp_path):
    """SSA v4 leads with 'Marked', ASS with 'Layer' — reading the file's
    own Format header is what keeps both working."""
    body = (
        "[Script Info]\nScriptType: v4.00\n\n"
        "[Events]\n"
        "Format: Marked, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        "Dialogue: Marked=0,0:00:02.00,0:00:04.00,Default,Bob,0000,0000,0000,,"
        "Legacy line\n"
    )
    back = convert.parse_to_segments(_write(tmp_path, "t.ssa", body))
    assert len(back) == 1
    assert back[0]["start"] == pytest.approx(2.0)
    assert back[0]["text"] == "Legacy line"
    assert back[0]["speaker"] == "Bob"


def test_comment_lines_are_not_subtitles(tmp_path):
    body = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        "Comment: 0,0:00:00.00,0:00:01.00,Default,,0,0,0,,editor note\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,real line\n"
    )
    back = convert.parse_to_segments(_write(tmp_path, "t.ass", body))
    assert [s["text"] for s in back] == ["real line"]


def test_styling_overrides_are_stripped(tmp_path):
    body = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,"
        "{\\an8\\i1}styled{\\r} text\\Nsecond line\n"
    )
    back = convert.parse_to_segments(_write(tmp_path, "t.ass", body))
    assert back[0]["text"] == "styled text second line"


def test_detected_by_content_when_the_extension_is_unknown(tmp_path):
    """An ASS file starts with '[', which the JSON sniff would claim."""
    path = _write(tmp_path, "subs.dat", get_writer("ass")(SEGMENTS, ""))
    back = convert.parse_to_segments(path)
    assert len(back) == 2


def test_a_json_transcript_is_still_detected_as_json(tmp_path):
    """Guard the ordering change: JSON must not be captured by the ASS sniff."""
    path = _write(tmp_path, "t.json",
                  '[{"start": 0, "end": 1, "text": "json wins"}]')
    back = convert.parse_to_segments(path)
    assert back[0]["text"] == "json wins"


def test_dialogue_outside_an_events_section_is_ignored(tmp_path):
    body = (
        "[Script Info]\n"
        "Dialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,not an event\n"
    )
    assert convert.parse_to_segments(_write(tmp_path, "t.ass", body)) == []


def test_unparseable_timestamps_are_skipped_not_fatal(tmp_path):
    body = (
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        "Dialogue: 0,NOPE,0:00:02.00,Default,,0,0,0,,bad\n"
        "Dialogue: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,good\n"
    )
    back = convert.parse_to_segments(_write(tmp_path, "t.ass", body))
    assert [s["text"] for s in back] == ["good"]


def test_convert_srt_to_ass(tmp_path):
    srt = "1\n00:00:01,000 --> 00:00:02,500\nfrom srt\n\n"
    src = _write(tmp_path, "in.srt", srt)
    out = convert.convert_file(src, "ass")
    assert out.endswith(".ass")
    body = open(out, encoding="utf-8").read()
    assert "[Script Info]" in body
    assert "from srt" in body


def test_convert_ass_to_srt(tmp_path):
    src = _write(tmp_path, "in.ass", get_writer("ass")(SEGMENTS, ""))
    out = convert.convert_file(src, "srt")
    body = open(out, encoding="utf-8").read()
    assert "-->" in body
    assert "Hello world" in body
