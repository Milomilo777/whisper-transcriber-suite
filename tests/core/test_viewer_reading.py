"""Reading paragraphs preserve the timeline and logical Unicode."""
from __future__ import annotations

import errno
import os
from types import SimpleNamespace

import pytest

from app.dialogs import transcript_viewer as tv
from app.dialogs import viewer_exports
from core import segment_ops


def test_reading_groups_persian_and_chinese_by_speaker_and_pause():
    cues = [
        {"start": 1, "end": 2, "speaker": "الف", "text": "سلام، حال شما چطور است؟"},
        {"start": 3, "end": 4, "speaker": "الف", "text": "خوبم، ممنون."},
        {"start": 6, "end": 7, "speaker": "ب", "text": "你好。"},
        {"start": 7, "end": 8, "speaker": "ب", "text": "今天很好。"},
        {"start": 11, "end": 12, "speaker": "ب", "text": "再见！"},
    ]
    paragraphs = segment_ops.reading_paragraphs(cues)
    assert [(p.start, p.speaker, p.text) for p in paragraphs] == [
        (1, "الف", "سلام، حال شما چطور است؟ خوبم، ممنون."),
        (6, "ب", "你好。今天很好。"),
        (11, "ب", "再见！"),
    ]
    for fmt in ("txt", "md"):
        body = segment_ops.render_reading(paragraphs, fmt)
        assert body.count("\n\n") == 2
        assert "你好。今天很好。" in body
        assert "خوبم" in body
        assert "\u202b" not in body


def test_reading_caps_a_single_long_unpunctuated_cue():
    text = "这是没有标点的一段长中文" * 80
    paragraphs = segment_ops.reading_paragraphs([{"start": 13, "end": 20, "text": text}])
    assert len(paragraphs) > 1
    assert all(len(p.text) <= 420 and p.start == 13 for p in paragraphs)
    assert "".join(p.text for p in paragraphs) == text


def test_reading_export_refuses_an_existing_file(tmp_path, monkeypatch):
    viewer = tv.TranscriptViewer.__new__(tv.TranscriptViewer)
    viewer.segments = [{"start": 1, "end": 2, "text": "سلام"}]
    viewer.json_path = str(tmp_path / "transcript.json")
    target = tmp_path / "transcript.txt"
    target.write_bytes(b"original")
    errors = []
    monkeypatch.setattr(tv.filedialog, "asksaveasfilename", lambda **k: str(target))
    monkeypatch.setattr(tv, "show_error", lambda *a, **k: errors.append(a))
    viewer._export_paragraphs("txt")
    assert target.read_bytes() == b"original"
    assert errors
    elsewhere = tmp_path / "transcript.paragraphs.txt"
    monkeypatch.setattr(tv.filedialog, "asksaveasfilename", lambda **k: str(elsewhere))
    monkeypatch.setattr(tv, "notify", lambda *a, **k: None)
    viewer._export_paragraphs("txt")
    assert elsewhere.read_text(encoding="utf-8") == "سلام\n"


@pytest.mark.parametrize("destination_exists", [False, True])
def test_new_paragraph_export_on_a_volume_without_hard_links(tmp_path, monkeypatch, destination_exists):
    destination = tmp_path / "paragraphs.md"
    if destination_exists:
        destination.write_bytes(b"earlier export")

    def unsupported_link(*_args):
        raise OSError(errno.ENOTSUP, "hard links unavailable")

    monkeypatch.setattr(viewer_exports, "os", SimpleNamespace(
        name="posix", path=os.path, stat=os.stat, unlink=os.unlink, link=unsupported_link,
    ))
    content = "سلام\n".encode("utf-8")
    if destination_exists:
        with pytest.raises(FileExistsError):
            viewer_exports.write_atomically(str(destination), content, create_only=True)
        assert destination.read_bytes() == b"earlier export"
    else:
        viewer_exports.write_atomically(str(destination), content, create_only=True)
        assert destination.read_bytes() == content
    assert list(tmp_path.iterdir()) == [destination]
