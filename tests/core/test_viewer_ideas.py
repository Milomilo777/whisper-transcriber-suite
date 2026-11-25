"""Windowless tests for the viewer's shared edit transactions."""
from __future__ import annotations

import json
from types import SimpleNamespace

from app.dialogs import transcript_viewer as tv


def _viewer(tmp_path):
    viewer = tv.TranscriptViewer.__new__(tv.TranscriptViewer)
    viewer.segments = [
        {"start": 0, "end": 2, "text": "cat cat", "speaker": "A", "words": [
            {"start": 0, "end": 1, "word": "cat"}, {"start": 1, "end": 2, "word": "cat"},
        ]},
        {"start": 2, "end": 3, "text": "cat", "speaker": "B"},
    ]
    viewer.json_path = str(tmp_path / "test.json")
    viewer._populate_listbox = lambda: None
    viewer._queue_exports = lambda _payload: None
    viewer._find_dialog = None
    viewer._active_segment_idx = None
    return viewer


def test_replace_all_undo_restores_words_as_one_step(tmp_path, monkeypatch):
    viewer = _viewer(tmp_path)
    original = viewer.segments[0]
    dialog = tv.FindReplaceDialog.__new__(tv.FindReplaceDialog)
    dialog.viewer = viewer
    dialog._needle = lambda: "cat"
    dialog.replace_var = SimpleNamespace(get=lambda: "dog")
    dialog.case_var = SimpleNamespace(get=lambda: True)
    dialog._forget_match = lambda: None
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)

    dialog.replace_all()
    assert [cue["text"] for cue in viewer.segments] == ["dog dog", "dog"]
    assert "words" not in viewer.segments[0]
    viewer._undo_edit()
    assert viewer.segments[0] == original
    assert viewer.segments[0]["words"][1]["word"] == "cat"
    assert viewer.segments[1]["text"] == "cat"
    assert not viewer._dirty
    viewer._redo_edit()
    assert [cue["text"] for cue in viewer.segments] == ["dog dog", "dog"]


def test_undo_after_save_leaves_the_disk_at_saved_version(tmp_path, monkeypatch):
    viewer = _viewer(tmp_path)
    monkeypatch.setattr(tv, "notify", lambda *a, **k: None)
    monkeypatch.setattr(tv.simpledialog, "askstring", lambda *a, **k: "Renamed")
    viewer._rename_speaker("A")
    viewer._save_changes()
    viewer._undo_edit()

    assert viewer._dirty
    assert viewer.segments[0]["speaker"] == "A"
    assert json.loads((tmp_path / "test.json").read_text())[0]["speaker"] == "Renamed"
    viewer._redo_edit()
    assert not viewer._dirty


def test_history_caps_actions_and_shares_unchanged_word_data(tmp_path):
    viewer = _viewer(tmp_path)
    unchanged = viewer.segments[0]
    viewer.segments.extend({"start": n, "end": n + 1, "text": str(n)} for n in range(3, 3902))
    for change in range(40):
        viewer._apply_edit([*viewer.segments[:-1], {"text": str(change)}], "Edit")
    for _ in range(40):
        viewer._undo_edit()
    assert viewer.segments[-1]["text"] == "7"
    assert viewer.segments[0] is unchanged
    assert viewer.segments[0]["words"] is unchanged["words"]
    viewer._apply_edit([*viewer.segments[:-1], {"text": "branch"}], "Edit")
    viewer._redo_edit()
    assert viewer.segments[-1]["text"] == "branch"
