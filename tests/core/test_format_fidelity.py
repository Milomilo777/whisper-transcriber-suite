"""Subtitle formats keep the text exactly: edits, escapes and round trips.

Each test pins one defect of the writers in ``core.writers`` or the
parsers in ``core.convert``: an edited ``text`` hidden behind a stale
``words`` list, markup characters lost or invented on a write/parse pair,
wrong default timestamps, and inputs the converter could not read.
The per-format property run lives in ``test_format_roundtrip_property.py``.
"""
from __future__ import annotations

import logging
import re

import pytest

from core import chapters, convert
from core.writers import ass, bilingual_srt, elan, inqscribe, json_writer, srt, tsv, vtt

BS = chr(92)


def _parse(tmp_path, name: str, body: str | bytes) -> list[dict]:
    p = tmp_path / name
    if isinstance(body, bytes):
        p.write_bytes(body)
    else:
        p.write_text(body, encoding="utf-8", newline="\n")
    return convert.parse_to_segments(str(p))


def _texts(segs: list[dict]) -> list[str]:
    return [s["text"] for s in segs]


# ------------------------------------------------- 1. stale words after an edit

_STALE = {
    "start": 0.0, "end": 2.0, "text": "Hello there world",
    "words": [
        {"start": 0.0, "end": 0.5, "word": "Hello"},
        {"start": 0.6, "end": 1.0, "word": "wrold"},
    ],
}


def test_words_match_text_ignores_whitespace_only():
    from core.writers.base import words_match_text

    seg = {"text": "Hello world.", "words": [{"word": " Hello"}, {"word": " world."}]}
    assert words_match_text(seg)
    cjk = {"text": "你好", "words": [{"word": "你"}, {"word": "好"}]}
    assert words_match_text(cjk)
    assert not words_match_text(_STALE)
    assert not words_match_text({"text": "Hello", "words": []})
    assert not words_match_text({"text": "Hello", "words": "Hello"})


def test_vtt_writes_edited_text_when_words_are_stale():
    out = vtt.write([_STALE])
    assert "Hello there world" in out
    assert "wrold" not in out


def test_ass_writes_edited_text_when_words_are_stale():
    out = ass.write([_STALE])
    assert "Hello there world" in out
    assert "wrold" not in out
    assert BS + "k" not in out


def test_karaoke_kept_when_words_match_text():
    seg = {
        "start": 0.0, "end": 1.0, "text": "Hello world",
        "words": [
            {"start": 0.0, "end": 0.4, "word": "Hello"},
            {"start": 0.5, "end": 1.0, "word": "world"},
        ],
    }
    assert "<c>Hello</c>" in vtt.write([seg])
    assert "{" + BS + "k" in ass.write([seg])


def test_convert_json_to_vtt_keeps_the_edit(tmp_path):
    import json

    segs = _parse(tmp_path, "edited.json", json.dumps([_STALE]))
    out = vtt.write(segs)
    assert "Hello there world" in out and "wrold" not in out


# ------------------------------------------------- 2. SRT / VTT markup

def test_srt_parser_keeps_angle_brackets_that_are_not_tags(tmp_path):
    body = "1\n00:00:00,000 --> 00:00:01,000\nif a < b and c > d\n"
    assert _texts(_parse(tmp_path, "a.srt", body)) == ["if a < b and c > d"]


def test_srt_parser_still_strips_formatting_tags(tmp_path):
    body = ('1\n00:00:00,000 --> 00:00:01,000\n'
            '<i>one</i> <b>two</b> <font color="#ff0000">three</font>\n')
    assert _texts(_parse(tmp_path, "a.srt", body)) == ["one two three"]


def test_vtt_parser_decodes_entities(tmp_path):
    body = "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n&gt;&gt; Tom &amp; Jerry &lt;3\n"
    assert _texts(_parse(tmp_path, "a.vtt", body)) == [">> Tom & Jerry <3"]


def test_vtt_escapes_markup_and_round_trips(tmp_path):
    seg = {"start": 0.0, "end": 1.0, "text": "if a < b & c > d --> e <b>x</b>",
           "speaker": "A<B"}
    out = vtt.write([seg])
    payload = out.splitlines()[3]
    assert "<" not in payload and ">" not in payload
    assert "&lt;" in payload and "&amp;" in payload
    back = _parse(tmp_path, "a.vtt", out)
    assert _texts(back) == ["A<B: if a < b & c > d --> e <b>x</b>"]


def test_vtt_escapes_karaoke_word_tokens(tmp_path):
    seg = {"start": 0.0, "end": 1.0, "text": "<b> &",
           "words": [{"start": 0.0, "end": 0.5, "word": "<b>"},
                     {"start": 0.5, "end": 1.0, "word": "&"}]}
    out = vtt.write([seg])
    assert "<c>&lt;b&gt;</c>" in out and "<c>&amp;</c>" in out
    assert _texts(_parse(tmp_path, "k.vtt", out)) == ["<b> &"]


def test_vtt_parser_strips_voice_class_and_timestamp_tags(tmp_path):
    body = ("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\n"
            "<v Bob>hi<00:00:00.500><c.yellow> there</c></v>\n")
    assert _texts(_parse(tmp_path, "t.vtt", body)) == ["hi there"]


# ------------------------------------------------- 3. ASS escapes

@pytest.mark.parametrize("text", [
    "use {braces} here",
    "C:" + BS + "path" + BS + "new",
    "literal " + BS + "N token",
    "{" + BS + "k5} not a tag",
    BS + "{" + BS + "}",
    "ends with " + BS,
])
def test_ass_round_trips_braces_and_backslashes(tmp_path, text):
    out = ass.write([{"start": 0.0, "end": 1.0, "text": text}])
    assert _texts(_parse(tmp_path, "a.ass", out)) == [text]


def test_ass_parser_drops_override_blocks_and_reads_line_breaks(tmp_path):
    out = ass.write([{"start": 0.0, "end": 1.0, "text": "x"}]).replace(
        ",x\n", ",{" + BS + "an8}one" + BS + "Ntwo {" + BS + "k20}three" + BS + "hfour\n")
    assert _texts(_parse(tmp_path, "b.ass", out)) == ["one two three four"]


# ------------------------------------------------- 4. ELAN

def test_elan_missing_end_defaults_to_start():
    out = elan.write([{"start": 5.0, "text": "hi"}])
    assert re.findall(r'TIME_VALUE="(\d+)"', out) == ["5000", "5000"]


def test_elan_media_url_is_a_valid_file_uri(tmp_path):
    media = tmp_path / "my video #1 سلام.mp4"
    out = elan.write([{"start": 0.0, "end": 1.0, "text": "hi"}], str(media))
    m = re.search(r'MEDIA_URL="([^"]+)"', out)
    assert m is not None
    url = m.group(1)
    assert url == media.resolve().as_uri()
    assert " " not in url and "#" not in url and not url.startswith("file:////")


# ------------------------------------------------- 5. timing edge cases

def test_ass_writes_hours_beyond_nine():
    assert ass.fmt_ass_time(11 * 3600 + 1.5) == "11:00:01.50"


def test_ass_long_media_round_trips_the_hour(tmp_path):
    out = ass.write([{"start": 36000.0, "end": 36001.0, "text": "late"}])
    seg = _parse(tmp_path, "long.ass", out)[0]
    assert seg["start"] == pytest.approx(36000.0)


def test_srt_skips_blank_cues_and_numbers_contiguously():
    out = srt.write([
        {"start": 0.0, "end": 1.0, "text": "one"},
        {"start": 1.0, "end": 2.0, "text": "   "},
        {"start": 2.0, "end": 3.0, "text": "two"},
    ])
    assert out.split("\n\n")[1].startswith("2\n00:00:02,000")
    assert "\n\n\n" not in out


def test_vtt_skips_blank_cues():
    out = vtt.write([{"start": 0.0, "end": 1.0, "text": ""},
                     {"start": 1.0, "end": 2.0, "text": "x"}])
    assert "00:00:00.000" not in out


@pytest.mark.parametrize("writer", [srt.write, vtt.write])
def test_srt_vtt_clamp_end_before_start(writer):
    out = writer([{"start": 5.0, "end": 2.0, "text": "x"}])
    assert re.search(r"00:00:05[,.]000 --> 00:00:05[,.]000", out)


def test_json_and_tsv_default_missing_end_to_start():
    import json

    assert json.loads(json_writer.write([{"start": 5.0, "text": "x"}]))[0]["end"] == 5.0
    assert tsv.write([{"start": 5.0, "text": "x"}]).splitlines()[1] == "5000\t5000\tx"


# ------------------------------------------------- 6. whitespace-only body line

def test_vtt_cue_with_whitespace_only_first_line_keeps_its_text(tmp_path):
    body = ("WEBVTT\nKind: captions\nLanguage: en\n\n"
            "00:00:00.030 --> 00:00:02.270 align:start position:0%\n"
            " \n"
            "welcome<00:00:00.539><c> back</c>\n"
            "\n"
            "00:00:02.270 --> 00:00:04.000 align:start position:0%\n"
            "welcome back\n"
            " \n")
    assert _texts(_parse(tmp_path, "yt.vtt", body)) == ["welcome back", "welcome back"]


def test_srt_with_whitespace_separator_lines_still_splits_cues(tmp_path):
    body = ("1\n00:00:00,000 --> 00:00:01,000\nhello\n   \n"
            "2\n00:00:01,000 --> 00:00:02,000\nworld\n")
    assert _texts(_parse(tmp_path, "w.srt", body)) == ["hello", "world"]


def test_vtt_note_block_is_not_cue_text(tmp_path):
    body = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nhello\n\n"
            "NOTE a comment\n\nintro\n00:00:01.000 --> 00:00:02.000\nworld\n")
    assert _texts(_parse(tmp_path, "n.vtt", body)) == ["hello", "world"]


# ------------------------------------------------- P5-15 timecodes without fraction

def test_cue_timecode_without_fraction_is_read(tmp_path, caplog):
    body = ("1\n00:00:01 --> 00:00:03\nwhole seconds\n\n"
            "2\n00:00:04,000 --> broken\nlost\n\n"
            "3\n00:00:05,000 --> 00:00:06,000\nlast\n")
    with caplog.at_level(logging.WARNING, logger="core.convert"):
        segs = _parse(tmp_path, "f.srt", body)
    assert _texts(segs) == ["whole seconds", "last"]
    assert segs[0]["start"] == 1.0 and segs[0]["end"] == 3.0
    assert "skipped 1 cue" in caplog.text


# ------------------------------------------------- 7. encodings and JSON shapes

def test_utf16_srt_is_read(tmp_path):
    body = "1\n00:00:00,000 --> 00:00:01,000\nسلام دنیا\n"
    for enc in ("utf-16", "utf-16-le", "utf-16-be"):
        raw = body.encode(enc)
        assert _texts(_parse(tmp_path, f"u_{enc}.srt", raw)) == ["سلام دنیا"]


def test_legacy_codepage_srt_gets_a_clear_error(tmp_path):
    raw = "1\n00:00:00,000 --> 00:00:01,000\nسلام\n".encode("cp1256")
    with pytest.raises(convert.ConvertError, match="Windows-1256"):
        _parse(tmp_path, "legacy.srt", raw)


def test_openai_verbose_json_is_accepted(tmp_path):
    import json

    payload = {"text": "hi there", "language": "en",
               "segments": [{"id": 0, "start": 0.0, "end": 1.0, "text": " hi there"}]}
    assert _texts(_parse(tmp_path, "oa.json", json.dumps(payload))) == ["hi there"]


def test_json_object_without_segments_still_rejected(tmp_path):
    with pytest.raises(convert.ConvertError):
        _parse(tmp_path, "bad.json", '{"foo": 1}')


# ------------------------------------------------- P5-04 bilingual SRT

def test_bilingual_srt_empty_original_writes_translation_alone(tmp_path):
    segs = [{"start": 0.0, "end": 1.0, "text": ""},
            {"start": 1.0, "end": 2.0, "text": ""},
            {"start": 2.0, "end": 3.0, "text": "hi"}]
    out = bilingual_srt.write(segs, ["سلام", "", "درود"])
    assert "\n\n\n" not in out
    back = _parse(tmp_path, "bi.srt", out)
    assert _texts(back) == ["سلام", "hi درود"]


# ------------------------------------------------- InqScribe

def test_inqscribe_text_with_timestamp_round_trips(tmp_path):
    texts = ["see [00:01] here", "[00:00:02.00] starts", BS + "[1:02] odd", "x" + BS * 2 + "[0:01]"]
    segs = [{"start": float(i), "end": float(i) + 1, "text": t} for i, t in enumerate(texts)]
    back = _parse(tmp_path, "q.inqscr", inqscribe.write(segs))
    assert _texts(back) == texts


def test_inqscribe_plain_files_parse_as_before(tmp_path):
    body = "[00:00:01.00]one [00:00:02.50] two\n[00:00:04.00]three\n"
    assert _texts(_parse(tmp_path, "p.inqscr", body)) == ["one", "two", "three"]


# ------------------------------------------------- optional: chapters

def test_chapter_title_keeps_decimals_and_titles():
    segs = [{"start": 0.0, "end": 1.0, "text": "Version 2.0 is out. Next part"}]
    b = chapters.detect_chapter_boundaries(segs)[0]
    assert chapters.heuristic_title(segs, b) == "Version 2.0 is out"
    segs = [{"start": 0.0, "end": 1.0, "text": "Dr. Smith said hi. Then more"}]
    assert chapters.heuristic_title(segs, b) == "Dr. Smith said hi"


def test_chapters_survive_none_start_and_non_string_text():
    segs = [{"start": None, "end": 1.0, "text": 123},
            {"start": 1.0, "end": None, "text": None},
            {"start": 2.0, "end": 3.0, "text": "ok"}]
    out = chapters.build_chapters(segs)
    assert out and out[0]["title"] == "123 ok"


# ------------------------------------------------- review round 1

def test_vtt_whitespace_separator_ends_the_cue(tmp_path):
    body = ("WEBVTT\n\ncue1\n00:00:01.000 --> 00:00:02.000\nA\n   \n"
            "cue2\n00:00:03.000 --> 00:00:04.000\nB\n   \n"
            "NOTE a comment\n   \n00:00:05.000 --> 00:00:06.000\nC\n")
    assert _texts(_parse(tmp_path, "ws.vtt", body)) == ["A", "B", "C"]


def test_unreadable_timing_does_not_swallow_the_next_cue(tmp_path):
    body = ("1\n00:00:01,000 --> junk\nlost\n  \n"
            "2\n00:00:02,000 --> 00:00:03,000\nkept\n")
    assert _texts(_parse(tmp_path, "j.srt", body)) == ["kept"]


@pytest.mark.parametrize("line", [
    "00:00:01,000 --> 00:00:02,000;",
    chr(0x200B) + "00:00:01,000 --> 00:00:02,000",
    "00:00:01,000123 --> 00:00:02,000456",
])
def test_lenient_timing_lines(tmp_path, line):
    segs = _parse(tmp_path, "l.srt", f"1\n{line}\nhi\n")
    assert _texts(segs) == ["hi"] and segs[0]["start"] == 1.0


def test_spacing_only_edit_reaches_karaoke_formats(tmp_path):
    words = [{"start": 0.1 * i, "end": 0.1 * i + 0.1, "word": w}
             for i, w in enumerate(["see", "you", "to", "day"])]
    seg = {"start": 0.0, "end": 1.0, "text": "see you today", "words": words}
    for name, writer in (("s.vtt", vtt.write), ("s.ass", ass.write)):
        assert _texts(_parse(tmp_path, name, writer([seg]))) == ["see you today"]
    assert "<c>to</c><00:00:00.300><c>day</c>" in vtt.write([seg])


def test_cjk_karaoke_has_no_inserted_spaces(tmp_path):
    words = [{"start": 0.0, "end": 0.5, "word": "你好"},
             {"start": 0.5, "end": 1.0, "word": "世界"}]
    seg = {"start": 0.0, "end": 1.0, "text": "你好世界", "words": words}
    for name, writer in (("c.vtt", vtt.write), ("c.ass", ass.write)):
        assert _texts(_parse(tmp_path, name, writer([seg]))) == ["你好世界"]


@pytest.mark.parametrize("end", ["abc", float("nan"), float("inf"), 10 ** 400, -5, 1.0])
def test_tsv_bad_or_early_end_is_clamped_to_start(end):
    row = tsv.write([{"start": 2.0, "end": end, "text": "x"}]).splitlines()[1]
    assert row == "2000\t2000\tx"


def test_html_like_tags_from_other_tools_are_removed(tmp_path):
    srt_body = "1\n00:00:00,000 --> 00:00:01,000\nline<br>two <span>x</span>\n"
    assert _texts(_parse(tmp_path, "h.srt", srt_body)) == ["line two x"]
    vtt_body = ("WEBVTT\n\n00:00:00.000 --> 00:00:01.000\n"
                '<font color="#f00">Red</font> <strong>s</strong><br/>t\n')
    assert _texts(_parse(tmp_path, "h.vtt", vtt_body)) == ["Red s t"]


def test_utf32_and_bomless_utf16_with_little_ascii(tmp_path):
    body = "1\n00:00:00,000 --> 00:00:01,000\nسلام\n"
    assert _texts(_parse(tmp_path, "u32.srt", body.encode("utf-32"))) == ["سلام"]
    persian = ("1\n00:00:01,000 --> 00:00:02,000\n" + "سلام " * 400).encode("utf-16-le")
    with pytest.raises(convert.ConvertError, match="NUL"):
        _parse(tmp_path, "nobom.srt", persian)


def test_inqscribe_long_backslash_runs_stay_fast(tmp_path):
    import time

    text = BS * 20000 + "[00:01] end"
    t0 = time.perf_counter()
    back = _parse(tmp_path, "slow.inqscr", inqscribe.write([{"start": 0.0, "text": text}]))
    assert time.perf_counter() - t0 < 2.0
    assert _texts(back) == [text]


@pytest.mark.parametrize("text, title", [
    ("... so we went home. Then more", "so we went home"),
    ("!!! Wow that was fun. ok", "Wow that was fun"),
    ("The answer is no. Then we left", "The answer is no"),
    ("So did I. Then we left.", "So did I"),
    ("U.S. Army is big. Next", "U.S. Army is big"),
    ("سلام دنیا؟ بعد", "سلام دنیا"),
    ("你好。世界", "你好"),
    ("two\nlines", "two lines"),
])
def test_chapter_title_sentence_edges(text, title):
    segs = [{"start": 0.0, "end": 1.0, "text": text}]
    b = chapters.detect_chapter_boundaries(segs)[0]
    assert chapters.heuristic_title(segs, b) == title

