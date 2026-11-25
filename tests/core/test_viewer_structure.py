"""Regression tests for split/join in the transcript viewer."""
from __future__ import annotations

import json

from app.dialogs import transcript_viewer as tv
from core import segment_ops


def _viewer(tmp_path, cues):
    viewer = tv.TranscriptViewer.__new__(tv.TranscriptViewer)
    viewer.segments = cues
    viewer.json_path = str(tmp_path / "cues.json")
    viewer._find_dialog = None
    viewer._active_segment_idx = None
    viewer._populate_listbox = lambda: None
    viewer._queue_exports = lambda _text: None
    return viewer


def test_viewer_split_join_uses_word_clocks_and_keeps_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(tv, "notify", lambda *a, **k: None)
    original = {
        "start": 1.0, "end": 10.0, "text": "hello world", "speaker": "A", "language": "en",
        "words": [{"start": 2.0, "end": 3.0, "word": "hello", "source": 1},
                  {"start": 6.0, "end": 9.0, "word": "world"}],
        "translation": "سلام دنیا", "metadata": {"note": "keep"},
    }
    viewer = _viewer(tmp_path, [original])
    viewer._split_at_caret(0, 5, 4)
    left, right = viewer.segments
    assert (left["end"], right["start"]) == (3.0, 6.0)
    assert (left["translation"], right["translation"]) == ("سلام", "دنیا")
    assert left["words"] + right["words"] == original["words"]
    assert left["metadata"] == right["metadata"] == original["metadata"]
    viewer._save_changes()
    saved_left = json.loads((tmp_path / "cues.json").read_text(encoding="utf-8"))[0]
    assert saved_left["metadata"] == original["metadata"]
    assert saved_left["words"][0]["source"] == 1
    assert saved_left["translation"] == "سلام"
    viewer._join_next(0)
    assert viewer.segments == [original]
    viewer._undo_edit()
    assert viewer.segments == [left, right]


def test_split_without_words_uses_characters_and_keeps_neighbor_identity(tmp_path):
    cue = {"start": 0.0, "end": 9.0, "text": "你好吗朋友一"}
    other = {"start": 9.0, "end": 11.0, "text": "第二句"}
    viewer = _viewer(tmp_path, [cue, other])
    viewer._split_at_caret(0, 2)
    assert [(s["text"], s["start"], s["end"]) for s in viewer.segments[:2]] == [
        ("你好", 0.0, 3.0), ("吗朋友一", 3.0, 9.0),
    ]
    assert viewer.segments[2] is other


def test_join_rejects_conflicting_fields_without_losing_text(tmp_path, monkeypatch):
    cues = [{"start": 0, "end": 1, "text": "Hello", "language": "en"},
            {"start": 1, "end": 2, "text": "你好", "language": "zh"}]
    viewer = _viewer(tmp_path, cues)
    notices = []
    monkeypatch.setattr(tv, "notify", lambda *a: notices.append(a))
    viewer._join_next(0)
    assert viewer.segments is cues
    assert not viewer._dirty
    assert notices


def test_split_cannot_cut_a_timed_word_or_erase_a_pair():
    cue = {"start": 0, "end": 5, "text": "hello world", "translation": "سلام دنیا",
           "words": [{"word": "hello", "start": 0, "end": 1},
                     {"word": "world", "start": 2, "end": 3}]}
    import pytest

    with pytest.raises(segment_ops.SegmentOpError):
        segment_ops.split_viewer_cue(cue, 3, 4)
    with pytest.raises(segment_ops.SegmentOpError):
        segment_ops.split_viewer_cue(cue, 5)
