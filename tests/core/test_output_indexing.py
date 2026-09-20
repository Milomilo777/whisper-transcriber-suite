"""Transcript outputs get an index instead of overwriting a previous run.

Re-transcribing a file used to overwrite its earlier .srt/.json. Now a
shared index is appended so the previous outputs survive:
name.srt + name.json -> name (1).srt + name (1).json (together).
"""
from __future__ import annotations

import json
import os

import core.transcriber as t


def test_indexed_path():
    assert t._indexed_path("/a/b/video.srt", 0) == "/a/b/video.srt"
    assert t._indexed_path("/a/b/video.srt", 1) == "/a/b/video (1).srt"
    assert t._indexed_path("/a/b/video.srt", 2) == "/a/b/video (2).srt"
    # Only the final extension is split off.
    assert t._indexed_path("/a/b/my.clip.json", 1) == "/a/b/my.clip (1).json"


def test_write_outputs_indexes_instead_of_overwriting(tmp_path, monkeypatch):
    # Stub the writers so no real model / transcription is needed.
    monkeypatch.setattr(t, "supported_formats", lambda: {"srt", "json"})
    monkeypatch.setattr(t, "is_binary", lambda f: False)
    monkeypatch.setattr(t, "get_writer", lambda f: (lambda seg, audio: f"{f}-data"))
    monkeypatch.setitem(t.config, "output_formats", ["srt", "json"])
    monkeypatch.setitem(t.config, "output_filename_template", "{base}.{ext}")

    base = str(tmp_path / "clip")
    first = sorted(os.path.basename(p) for p in
                   t._write_outputs(base, [], "audio.wav", formats=["srt", "json"]))
    second = sorted(os.path.basename(p) for p in
                    t._write_outputs(base, [], "audio.wav", formats=["srt", "json"]))
    third = sorted(os.path.basename(p) for p in
                   t._write_outputs(base, [], "audio.wav", formats=["srt", "json"]))

    assert first == ["clip.json", "clip.srt"]
    assert second == ["clip (1).json", "clip (1).srt"]   # shared index, no overwrite
    assert third == ["clip (2).json", "clip (2).srt"]
    # The original first-run files must still be on disk.
    assert (tmp_path / "clip.srt").exists()
    assert (tmp_path / "clip.json").exists()


def test_write_outputs_shares_one_index_across_formats(tmp_path, monkeypatch):
    # If only ONE of the set exists, both formats jump to the same next
    # index — never a mismatched name (1).srt + name.json pair.
    monkeypatch.setattr(t, "supported_formats", lambda: {"srt", "json"})
    monkeypatch.setattr(t, "is_binary", lambda f: False)
    monkeypatch.setattr(t, "get_writer", lambda f: (lambda seg, audio: f"{f}-data"))
    monkeypatch.setitem(t.config, "output_formats", ["srt", "json"])
    monkeypatch.setitem(t.config, "output_filename_template", "{base}.{ext}")

    base = str(tmp_path / "clip")
    (tmp_path / "clip.srt").write_text("pre-existing", encoding="utf-8")  # only srt exists

    out = sorted(os.path.basename(p) for p in
                 t._write_outputs(base, [], "audio.wav", formats=["srt", "json"]))
    assert out == ["clip (1).json", "clip (1).srt"]
    assert (tmp_path / "clip.srt").read_text(encoding="utf-8") == "pre-existing"


def _stub_writers(monkeypatch) -> None:
    monkeypatch.setattr(t, "supported_formats", lambda: {"srt", "json"})
    monkeypatch.setattr(t, "is_binary", lambda f: False)
    monkeypatch.setattr(t, "get_writer", lambda f: (lambda seg, audio: f"{f}-data"))
    monkeypatch.setitem(t.config, "output_formats", ["srt", "json"])
    monkeypatch.setitem(t.config, "output_filename_template", "{base}.{ext}")


def test_chapter_sidecar_shares_the_output_index(tmp_path, monkeypatch):
    """The auto-chapter sidecar must move with the transcript set.

    The viewer derives the sidecar path from the JSON it opened
    (``<stem>.chapters.json``). Writing it at the un-indexed base made a
    re-run's chapters invisible from the newly indexed transcript — and
    overwrote the previous run's file in place.
    """
    _stub_writers(monkeypatch)
    base = str(tmp_path / "clip")
    chapters = [{"start": 0.0, "end": 30.0, "title": "Intro"}]

    first = sorted(os.path.basename(p) for p in t._write_outputs(
        base, [], "audio.wav", formats=["srt", "json"], chapters=chapters,
    ))
    assert first == ["clip.chapters.json", "clip.json", "clip.srt"]

    second = sorted(os.path.basename(p) for p in t._write_outputs(
        base, [], "audio.wav", formats=["srt", "json"], chapters=chapters,
    ))
    assert second == [
        "clip (1).chapters.json", "clip (1).json", "clip (1).srt",
    ]
    # The first run's sidecar stays with its own transcript.
    assert (tmp_path / "clip.chapters.json").exists()
    payload = json.loads(
        (tmp_path / "clip (1).chapters.json").read_text(encoding="utf-8")
    )
    assert payload == chapters


def test_chapter_sidecar_absent_when_no_chapters(tmp_path, monkeypatch):
    _stub_writers(monkeypatch)
    base = str(tmp_path / "clip")
    out = t._write_outputs(base, [], "audio.wav", formats=["srt", "json"])
    assert sorted(os.path.basename(p) for p in out) == ["clip.json", "clip.srt"]
    assert not (tmp_path / "clip.chapters.json").exists()


def test_orphan_sidecar_bumps_the_shared_index(tmp_path, monkeypatch):
    """A sidecar already on disk (older version / manually kept) must not
    be overwritten: the whole set — transcripts AND sidecar — moves to
    the next free index."""
    _stub_writers(monkeypatch)
    base = str(tmp_path / "clip")
    (tmp_path / "clip.chapters.json").write_text("[]", encoding="utf-8")
    chapters = [{"start": 0.0, "end": 30.0, "title": "Intro"}]

    out = sorted(os.path.basename(p) for p in t._write_outputs(
        base, [], "audio.wav", formats=["srt", "json"], chapters=chapters,
    ))
    assert out == ["clip (1).chapters.json", "clip (1).json", "clip (1).srt"]
    assert (tmp_path / "clip.chapters.json").read_text(encoding="utf-8") == "[]"


def test_smtv_docx_filename_stays_fixed_even_when_other_formats_are_indexed(tmp_path, monkeypatch):
    """Real bug: smtv_docx used to share the srt/json collision index, so a
    pre-existing .srt/.json from an earlier run pushed the SMTV team's file
    to an unexpected " (1)" suffix on its very first write -- even though no
    smtv_docx had ever been written for that source before. The SMTV
    filename must stay exactly fixed (docs: "a fixed, recognisable name")
    regardless of what index the other formats land on."""
    from core.writers import smtv_docx_writer

    monkeypatch.setattr(t, "supported_formats", lambda: {"srt", "json", "smtv_docx"})
    monkeypatch.setattr(t, "is_binary", lambda f: f == "smtv_docx")
    monkeypatch.setattr(t, "get_writer", lambda f: (lambda seg, audio: f"{f}-data"))
    monkeypatch.setattr(smtv_docx_writer, "write_bytes", lambda *a, **kw: b"docx-bytes")
    monkeypatch.setitem(t.config, "output_formats", ["srt", "json", "smtv_docx"])
    monkeypatch.setitem(t.config, "output_filename_template", "{base}.{ext}")

    base = str(tmp_path / "MyEpisode")
    # Run 1: only srt/json requested -- no smtv_docx file exists yet anywhere.
    t._write_outputs(base, [], "audio.wav", formats=["srt", "json"], lang="ko")

    # Run 2: now smtv_docx is requested too. srt/json already exist from run 1
    # and correctly jump to index 1 -- but this is the smtv file's FIRST write.
    out2 = t._write_outputs(
        base, [], "audio.wav", formats=["srt", "json", "smtv_docx"], lang="ko",
    )
    smtv_name = next(os.path.basename(p) for p in out2 if p.endswith(".docx"))
    assert "(1)" not in smtv_name and "(2)" not in smtv_name
    assert any("(1)" in os.path.basename(p) for p in out2 if p.endswith((".srt", ".json")))

    # Run 3: re-run again -- srt/json move to index 2, smtv_docx overwrites
    # the SAME fixed path in place (canonical, latest-wins for the team file).
    out3 = t._write_outputs(
        base, [], "audio.wav", formats=["srt", "json", "smtv_docx"], lang="ko",
    )
    smtv_name_3 = next(os.path.basename(p) for p in out3 if p.endswith(".docx"))
    assert smtv_name_3 == smtv_name
    assert any("(2)" in os.path.basename(p) for p in out3 if p.endswith((".srt", ".json")))
