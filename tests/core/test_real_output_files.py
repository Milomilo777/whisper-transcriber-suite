"""Output files: one extension table, safe conversion targets, .otr fixes.

* The transcriber and ``core.convert`` share ``core.writers.FORMAT_EXTENSIONS``
  (ELAN -> .eaf, InqScribe -> .inqscr, Express Scribe -> .txt), so a
  transcription and a conversion give the target tool the same file type.
* File > Convert never replaces an existing different file at its default
  target, writes atomically, and refuses a source with no cues.
* ``.otr`` import keeps paragraphs typed without a timestamp; the Whisper JSON
  reader accepts a BOM.
"""
from __future__ import annotations

import json
import os

import pytest

import core.transcriber as tr
from core import convert
from core import writers
from core.integrations import otranscribe

SRT = "1\n00:00:00,000 --> 00:00:02,000\nhello there\n\n"


def _write(path, text, encoding="utf-8"):
    with open(path, "w", encoding=encoding, newline="\n") as f:
        f.write(text)


# --- one extension table (S03-3) ------------------------------------------


@pytest.mark.parametrize(
    "fmt, ext",
    [("elan", "eaf"), ("inqscribe", "inqscr"), ("express_scribe", "txt"),
     ("smtv_docx", "docx"), ("srt", "srt"), ("json", "json"), ("txt", "txt")],
)
def test_transcriber_and_converter_agree_on_every_extension(fmt, ext):
    assert writers.extension_for(fmt) == ext
    assert tr._FMT_EXTENSIONS.get(fmt, fmt) == ext
    assert convert.output_extension_for(fmt) == ext


def test_every_registry_format_maps_identically():
    for fmt in writers.supported_formats():
        assert tr._FMT_EXTENSIONS.get(fmt, fmt) == convert.output_extension_for(fmt)


def _stub_writers(monkeypatch, formats):
    monkeypatch.setattr(tr, "supported_formats", lambda: set(formats))
    monkeypatch.setattr(tr, "is_binary", lambda f: False)
    monkeypatch.setattr(tr, "get_writer", lambda f: (lambda seg, audio: f"{f}-data"))
    monkeypatch.setitem(tr.config, "output_filename_template", "{base}.{ext}")


def test_transcriber_writes_the_tool_extensions(tmp_path, monkeypatch):
    fmts = ["elan", "inqscribe", "express_scribe"]
    _stub_writers(monkeypatch, fmts)
    written = tr._write_outputs(str(tmp_path / "clip"), [], "a.wav", formats=fmts)
    assert sorted(os.path.basename(p) for p in written) == ["clip.eaf", "clip.inqscr", "clip.txt"]


def test_txt_and_express_scribe_together_do_not_overwrite_each_other(tmp_path, monkeypatch):
    fmts = ["txt", "express_scribe"]
    _stub_writers(monkeypatch, fmts)
    written = tr._write_outputs(str(tmp_path / "clip"), [], "a.wav", formats=fmts)
    names = {os.path.basename(p): open(p, encoding="utf-8").read() for p in written}
    assert names == {"clip.txt": "txt-data", "clip.express_scribe.txt": "express_scribe-data"}
    # A re-run indexes the pair together.
    again = tr._write_outputs(str(tmp_path / "clip"), [], "a.wav", formats=fmts)
    assert sorted(os.path.basename(p) for p in again) == [
        "clip (1).express_scribe.txt", "clip (1).txt"
    ]


def test_old_elan_and_inqscribe_files_still_convert(tmp_path):
    seg = [{"start": 0.0, "end": 1.0, "text": "hi"}]
    old_elan = tmp_path / "old.elan"
    _write(old_elan, writers.get_writer("elan")(seg, ""))
    old_inq = tmp_path / "old.inqscribe"
    _write(old_inq, writers.get_writer("inqscribe")(seg, ""))
    assert convert.parse_to_segments(str(old_elan))[0]["text"] == "hi"
    assert convert.parse_to_segments(str(old_inq))[0]["text"] == "hi"


# --- File > Convert target safety (S03-12, P5-13, P5-05) ------------------


def test_convert_keeps_an_existing_default_target(tmp_path):
    src = tmp_path / "talk.vtt"
    _write(src, "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello there\n")
    precious = tmp_path / "talk.srt"
    _write(precious, "PRECIOUS")
    out = convert.convert_file(str(src), "srt")
    assert out == str(tmp_path / "talk (1).srt")
    assert precious.read_text(encoding="utf-8") == "PRECIOUS"
    assert "hello there" in open(out, encoding="utf-8").read()
    out2 = convert.convert_file(str(src), "srt")
    assert out2 == str(tmp_path / "talk (2).srt")


def test_convert_overwrite_and_explicit_target_are_honoured(tmp_path):
    src = tmp_path / "talk.vtt"
    _write(src, "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nhello there\n")
    _write(tmp_path / "talk.srt", "OLD")
    assert convert.convert_file(str(src), "srt", overwrite=True) == str(tmp_path / "talk.srt")
    assert "hello there" in (tmp_path / "talk.srt").read_text(encoding="utf-8")
    chosen = tmp_path / "chosen.srt"
    _write(chosen, "OLD")
    assert convert.convert_file(str(src), "srt", str(chosen)) == str(chosen)
    assert "hello there" in chosen.read_text(encoding="utf-8")


def test_convert_of_a_cue_less_file_raises_and_keeps_the_target(tmp_path):
    src = tmp_path / "movie.srt"
    _write(src, "")
    target = tmp_path / "movie.vtt"
    _write(target, "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nkeep me\n")
    before = target.read_bytes()
    with pytest.raises(convert.ConvertError, match="no subtitle cues"):
        convert.convert_file(str(src), "vtt", overwrite=True)
    with pytest.raises(convert.ConvertError):
        convert.convert_file(str(src), "vtt", str(target))
    assert target.read_bytes() == before


def test_convert_write_failure_leaves_no_partial_file(tmp_path, monkeypatch):
    src = tmp_path / "talk.srt"
    _write(src, SRT)
    target = tmp_path / "talk.vtt"
    _write(target, "ORIGINAL")

    def boom(a, b):
        raise OSError("disk full")

    monkeypatch.setattr(convert.os, "replace", boom)
    with pytest.raises(OSError):
        convert.convert_file(str(src), "vtt", str(target))
    assert target.read_text(encoding="utf-8") == "ORIGINAL"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".part")] == []


def test_convert_output_is_lf_utf8(tmp_path):
    src = tmp_path / "talk.srt"
    _write(src, "1\n00:00:00,000 --> 00:00:02,000\nسلام\n\n")
    out = convert.convert_file(str(src), "vtt")
    data = open(out, "rb").read()
    assert b"\r\n" not in data
    assert "سلام" in data.decode("utf-8")


def test_convert_does_not_name_the_transcript_as_media(tmp_path):
    src = tmp_path / "talk.srt"
    _write(src, SRT)
    otr = json.loads(open(convert.convert_file(str(src), "otr"), encoding="utf-8").read())
    assert otr["media"] == ""
    md = open(convert.convert_file(str(src), "md"), encoding="utf-8").read()
    assert "talk.srt" not in md
    eaf = open(convert.convert_file(str(src), "elan"), encoding="utf-8").read()
    assert "talk.srt" not in eaf


# --- .otr import / export (P5-17, P5-09) ----------------------------------


def _otr_file(tmp_path, html, media_time=10.0):
    p = tmp_path / "edit.otr"
    _write(p, json.dumps({"text": html, "media": "", "media-time": media_time}))
    return str(p)


def _ts(seconds, body):
    return (
        f'<p><span class="timestamp" data-timestamp="{seconds}">00:0{int(seconds)}</span>'
        f" {body}</p>"
    )


def test_otr_import_keeps_a_paragraph_typed_without_a_timestamp(tmp_path):
    html = _ts(1.0, "first cue") + "<p>My own note here</p>" + _ts(3.0, "second cue")
    srt = otranscribe.otr_to_srt(_otr_file(tmp_path, html))
    assert "My own note here" in srt
    # Kept with the previous cue, in order, and the cue count is unchanged.
    assert srt.index("first cue") < srt.index("My own note here") < srt.index("second cue")
    assert srt.count(" --> ") == 2


def test_otr_import_keeps_leading_untimed_text(tmp_path):
    html = "<p>Title typed first</p>" + _ts(2.0, "a cue")
    srt = otranscribe.otr_to_srt(_otr_file(tmp_path, html))
    assert srt.startswith("1\n00:00:00,000 --> 00:00:02,000\nTitle typed first\n")
    assert "a cue" in srt


def test_otr_import_ignores_blank_untimed_paragraphs(tmp_path):
    html = _ts(1.0, "only cue") + "<p>  </p>\n"
    srt = otranscribe.otr_to_srt(_otr_file(tmp_path, html))
    assert srt.count(" --> ") == 1
    assert srt.rstrip().endswith("only cue")


def test_otr_round_trip_keeps_every_cue(tmp_path):
    src = tmp_path / "talk.srt"
    _write(src, SRT + "2\n00:00:03,000 --> 00:00:04,000\nsecond\n\n")
    otr = tmp_path / "talk.otr"
    _write(otr, otranscribe.srt_to_otr(str(src)))
    back = otranscribe.otr_to_srt(str(otr))
    assert "hello there" in back and "second" in back
    assert back.count(" --> ") == 2


def test_whisper_json_to_otr_accepts_a_bom(tmp_path):
    p = tmp_path / "talk.json"
    _write(p, json.dumps([{"start": 0, "end": 1, "text": "hi"}]), encoding="utf-8-sig")
    assert "hi" in json.loads(otranscribe.whisper_json_to_otr(str(p)))["text"]


def test_express_scribe_listed_first_still_leaves_txt_its_name(tmp_path, monkeypatch):
    fmts = ["express_scribe", "txt"]
    _stub_writers(monkeypatch, fmts)
    written = tr._write_outputs(str(tmp_path / "clip"), [], "a.wav", formats=fmts)
    names = {os.path.basename(p): open(p, encoding="utf-8").read() for p in written}
    assert names == {"clip.txt": "txt-data", "clip.express_scribe.txt": "express_scribe-data"}


def test_a_format_listed_twice_is_written_once_under_its_own_name(tmp_path, monkeypatch):
    fmts = ["srt", "srt", "json"]
    _stub_writers(monkeypatch, ["srt", "json"])
    written = tr._write_outputs(str(tmp_path / "clip"), [], "a.wav", formats=fmts)
    assert sorted(os.path.basename(p) for p in written) == ["clip.json", "clip.srt"]


def test_transcriber_table_is_a_copy_of_the_shared_one():
    assert tr._FMT_EXTENSIONS == writers.FORMAT_EXTENSIONS
    assert tr._FMT_EXTENSIONS is not writers.FORMAT_EXTENSIONS


@pytest.mark.parametrize("fmts", [["txt", "express_scribe"], ["express_scribe", "txt"]])
def test_server_surfaces_txt_and_express_scribe_separately(tmp_path, fmts):
    from types import SimpleNamespace

    from core.server import jobs

    plain = tmp_path / "clip.txt"
    express = tmp_path / "clip.express_scribe.txt"
    _write(plain, "1")
    _write(express, "2")
    job = SimpleNamespace(formats=fmts, work_dir=str(tmp_path))
    task = SimpleNamespace(output_paths=[str(plain), str(express)])
    mgr = SimpleNamespace(_collect_outputs_by_scan=lambda j: [])
    out = dict(jobs.JobManager._collect_outputs(mgr, job, task))  # type: ignore[arg-type]
    assert out == {"txt": str(plain), "express_scribe": str(express)}


def test_server_does_not_mistake_a_dotted_source_name_for_a_format(tmp_path):
    from types import SimpleNamespace

    from core.server import jobs

    p = tmp_path / "lecture.srt.json"
    _write(p, "[]")
    job = SimpleNamespace(formats=["srt", "json"], work_dir=str(tmp_path))
    task = SimpleNamespace(output_paths=[str(p)])
    mgr = SimpleNamespace(_collect_outputs_by_scan=lambda j: [])
    assert jobs.JobManager._collect_outputs(mgr, job, task) == [("json", str(p))]  # type: ignore[arg-type]
