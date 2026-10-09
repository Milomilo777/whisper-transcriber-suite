"""Transcript viewer: Save keeps EVERY output format next to the JSON in step.

Save used to rewrite only the SRT/VTT/ASS files, so the TXT, Markdown, Word and the other
exports kept the old text and the notice said nothing. Now each text and Word export that
still matches the transcript it was made from is rebuilt from the edited segments by the
same writers the transcription uses; anything that cannot be rebuilt faithfully (a file
edited elsewhere, a PDF, a writer that fails) is named in a warning and left as it is.
"""
from __future__ import annotations

import io
import json
import os
import zipfile
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402
import core.writers as writers  # noqa: E402

ALL_FORMATS = ["srt", "vtt", "ass", "txt", "md", "tsv", "lrc", "otr", "elan", "inqscribe", "docx", "json"]
OLD, NEW = "Hello world", "Edited in the viewer"


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def notices(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    got: list[tuple[str, str]] = []
    monkeypatch.setattr(tv, "notify", lambda _w, text, kind="info", **_k: got.append((text, kind)))
    return got


def _segments() -> list[dict[str, Any]]:
    return [
        {"start": 0.0, "end": 1.25, "text": OLD},
        {"start": 1.25, "end": 3.5, "text": "Second line here"},
    ]


def _write_outputs(tmp_path, formats: list[str]) -> str:
    """The transcriber's own writer, so the files match what a real run leaves."""
    from core.transcriber import _write_outputs as write_outputs

    written = write_outputs(str(tmp_path / "talk"), _segments(), str(tmp_path / "talk.mp4"), formats)
    return next(p for p in written if p.endswith(".json"))


def _open(root, json_path: str) -> tv.TranscriptViewer:
    viewer = tv.TranscriptViewer(root, json_path)
    viewer.withdraw()
    return viewer


def _close(viewer: tv.TranscriptViewer) -> None:
    viewer._dirty = False
    viewer._on_close()


def _edit(viewer: tv.TranscriptViewer, text: str = NEW) -> None:
    tv._set_segment_text(viewer.segments[0], text)
    viewer._dirty = True


def _body(path: str) -> str:
    """Text of an export: a Word file is its document.xml."""
    with open(path, "rb") as f:
        raw = f.read()
    if path.endswith(".docx"):
        return zipfile.ZipFile(io.BytesIO(raw)).read("word/document.xml").decode("utf-8")
    return raw.decode("utf-8")


def _outputs(tmp_path) -> list[str]:
    return sorted(str(p) for p in tmp_path.iterdir() if p.is_file() and not p.name.endswith(".json"))


def test_save_updates_every_output_format(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ALL_FORMATS)
    files = _outputs(tmp_path)
    assert len(files) == len(ALL_FORMATS) - 1  # every format wrote its own file
    assert all(OLD in _body(p) for p in files)
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        for path in files:
            body = _body(path)
            assert NEW in body and OLD not in body, os.path.basename(path)
        assert OLD not in _body(json_path) and NEW in _body(json_path)
        text, kind = notices[0]
        assert kind == "success"
        for name in ("talk.srt", "talk.txt", "talk.md", "talk.docx"):
            assert name in text
        assert not any(kind == "warning" for _t, kind in notices)
    finally:
        _close(viewer)


def test_save_keeps_the_title_the_files_were_made_with(root, tmp_path, notices) -> None:
    """The media file is gone: the Markdown and Word headings still say talk.mp4."""
    json_path = _write_outputs(tmp_path, ["md", "docx", "lrc", "json"])
    viewer = _open(root, json_path)
    try:
        assert viewer.media_path is None
        _edit(viewer)
        viewer._save_changes()
        assert _body(str(tmp_path / "talk.md")).startswith("# talk.mp4\n")
        assert "talk.mp4" in _body(str(tmp_path / "talk.docx"))
        assert NEW in _body(str(tmp_path / "talk.docx"))
        assert "[ti:talk]" in _body(str(tmp_path / "talk.lrc"))
        assert not any(kind == "warning" for _t, kind in notices)
    finally:
        _close(viewer)


def test_save_keeps_the_title_when_the_media_is_found(root, tmp_path, notices) -> None:
    (tmp_path / "talk.mp4").write_bytes(b"\x00")
    json_path = _write_outputs(tmp_path, ["md", "json"])
    viewer = _open(root, json_path)
    try:
        assert viewer.media_path is not None
        _edit(viewer)
        viewer._save_changes()
        assert _body(str(tmp_path / "talk.md")).startswith("# talk.mp4\n")
        assert NEW in _body(str(tmp_path / "talk.md"))
    finally:
        _close(viewer)


def test_express_scribe_text_file_is_updated(root, tmp_path, notices) -> None:
    """A .txt made by the Express Scribe writer is not the plain-text layout."""
    json_path = _write_outputs(tmp_path, ["express_scribe", "json"])
    txt = str(tmp_path / "talk.txt")
    old_layout = _body(txt)
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert NEW in _body(txt)
        assert _body(txt) == old_layout.replace(OLD, NEW)
    finally:
        _close(viewer)


def test_failing_writer_is_reported_and_the_rest_is_saved(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "txt", "md", "json"])
    before = _body(str(tmp_path / "talk.txt"))
    viewer = _open(root, json_path)

    def boom(_segments, _audio_path=""):
        raise RuntimeError("disk on fire")

    monkeypatch.setitem(writers.WRITERS, "txt", boom)
    try:
        _edit(viewer)
        viewer._save_changes()
        # The edits are on disk before anything is reported, and the other files followed.
        assert NEW in _body(json_path)
        assert NEW in _body(str(tmp_path / "talk.srt")) and NEW in _body(str(tmp_path / "talk.md"))
        assert _body(str(tmp_path / "talk.txt")) == before
        warnings = [t for t, kind in notices if kind == "warning"]
        assert len(warnings) == 1 and "talk.txt" in warnings[0]
        assert "talk.srt" not in warnings[0] and "talk.md" not in warnings[0]
        assert viewer._dirty is False
    finally:
        _close(viewer)


def test_failing_binary_writer_is_reported(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "docx", "json"])
    before = (tmp_path / "talk.docx").read_bytes()
    viewer = _open(root, json_path)

    def boom(_segments, _audio_path=""):
        raise RuntimeError("python-docx broke")

    monkeypatch.setitem(writers.BINARY_WRITERS, "docx", boom)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert (tmp_path / "talk.docx").read_bytes() == before
        assert NEW in _body(str(tmp_path / "talk.srt"))
        assert any(kind == "warning" and "talk.docx" in text for text, kind in notices)
        assert not list(tmp_path.glob("*.part"))
    finally:
        _close(viewer)


def test_text_file_edited_elsewhere_is_left_alone_and_named(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["txt", "md", "json"])
    txt = tmp_path / "talk.txt"
    hand_edit = txt.read_text(encoding="utf-8").replace("Second line here", "Edited by hand")
    txt.write_text(hand_edit, encoding="utf-8", newline="\n")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert txt.read_text(encoding="utf-8") == hand_edit
        assert NEW in _body(str(tmp_path / "talk.md"))
        assert any(kind == "warning" and "talk.txt" in text for text, kind in notices)
    finally:
        _close(viewer)


def test_word_file_edited_elsewhere_is_left_alone(root, tmp_path, notices) -> None:
    from docx import Document

    json_path = _write_outputs(tmp_path, ["docx", "srt", "json"])
    path = str(tmp_path / "talk.docx")
    doc = Document(path)
    doc.add_paragraph("Added by hand in Word")
    doc.save(path)
    after_hand_edit = (tmp_path / "talk.docx").read_bytes()
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert (tmp_path / "talk.docx").read_bytes() == after_hand_edit
        assert any(kind == "warning" and "talk.docx" in text for text, kind in notices)
    finally:
        _close(viewer)


def test_pdf_cannot_be_rebuilt_so_it_is_named(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    pdf = tmp_path / "talk.pdf"
    pdf.write_bytes(b"%PDF-1.4 not really")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert pdf.read_bytes() == b"%PDF-1.4 not really"
        assert any(kind == "warning" and "talk.pdf" in text for text, kind in notices)
    finally:
        _close(viewer)


def test_files_of_another_transcript_are_never_touched(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["json"])
    (tmp_path / "talk-notes.txt").write_text("my own notes\n", encoding="utf-8")
    (tmp_path / "other.md").write_text("# other\n", encoding="utf-8")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert (tmp_path / "talk-notes.txt").read_text(encoding="utf-8") == "my own notes\n"
        assert (tmp_path / "other.md").read_text(encoding="utf-8") == "# other\n"
    finally:
        _close(viewer)


def test_second_save_updates_the_other_formats_again(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["txt", "md", "docx", "json"])
    viewer = _open(root, json_path)
    try:
        _edit(viewer, "First edit")
        viewer._save_changes()
        _edit(viewer, "Second edit")
        viewer._save_changes()
        for name in ("talk.txt", "talk.md", "talk.docx"):
            assert "Second edit" in _body(str(tmp_path / name)), name
        assert not any(kind == "warning" for _t, kind in notices)
    finally:
        _close(viewer)


def test_persian_text_round_trips_into_every_format(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["txt", "md", "docx", "json"])
    viewer = _open(root, json_path)
    try:
        _edit(viewer, "سلام دنیا")
        viewer._save_changes()
        for name in ("talk.txt", "talk.md", "talk.docx"):
            assert "سلام دنیا" in _body(str(tmp_path / name)), name
        with open(json_path, encoding="utf-8") as f:
            assert json.load(f)[0]["text"] == "سلام دنیا"
    finally:
        _close(viewer)


def test_smtv_team_document_is_named_not_touched(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    smtv = tmp_path / "talk -Transcription in English – Translation in English.docx"
    smtv.write_bytes(b"PK team template")
    viewer = _open(root, json_path)
    try:
        _edit(viewer)
        viewer._save_changes()
        assert smtv.read_bytes() == b"PK team template"
        assert any(kind == "warning" and smtv.name in text for text, kind in notices)
    finally:
        _close(viewer)


def test_opening_builds_a_word_file_only_once(root, tmp_path, notices, monkeypatch) -> None:
    """A Word build of a long transcript takes seconds: the scan must not repeat it."""
    json_path = _write_outputs(tmp_path, ["docx", "json"])
    real = writers.BINARY_WRITERS["docx"]
    calls: list[str] = []

    def counting(segments, audio_path=""):
        calls.append(audio_path)
        return real(segments, audio_path)

    monkeypatch.setitem(writers.BINARY_WRITERS, "docx", counting)
    viewer = _open(root, json_path)
    try:
        assert calls == ["talk.mp4"]
    finally:
        _close(viewer)
