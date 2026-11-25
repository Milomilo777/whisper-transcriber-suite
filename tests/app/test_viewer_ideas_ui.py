"""Desktop coverage for transcript viewer edit, reading and compare controls."""
from __future__ import annotations

import json
import shutil
from tkinter import ttk

import pytest

from app.dialogs import transcript_viewer as tv
from core.history import HistoryDB
from core.sample_clip import bundled_clip_path

tk = pytest.importorskip("tkinter")


def test_viewer_edit_split_read_and_compare_on_desktop(tmp_path, monkeypatch):
    original = tmp_path / "sample.json"
    media = tmp_path / "sample.mp3"
    clip = bundled_clip_path()
    assert clip
    shutil.copyfile(clip, media)
    original.write_text(json.dumps([
        {"start": 0, "end": 3, "text": "Hello world", "speaker": "A"},
        {"start": 5, "end": 7, "text": "سلام، حال شما چطور است؟", "speaker": "ب"},
        {"start": 10, "end": 12, "text": "你好。"},
    ], ensure_ascii=False), encoding="utf-8")
    result = tmp_path / "sample (1).json"
    result.write_text('[{"start":0,"end":3,"text":"Different wording"}]', encoding="utf-8")
    monkeypatch.setattr(tv, "notify", lambda *a, **k: None)
    monkeypatch.setattr(tv, "_try_load_vlc", lambda: (None, ""))
    root = tk.Tk()
    root.withdraw()
    viewer = tv.TranscriptViewer(root, str(original), media_path=str(media))
    with HistoryDB(tmp_path / "history.db") as history:
        try:
            exit_answers = []

            def edit_draft():
                dialog = next(child for child in viewer.winfo_children() if isinstance(child, tv.EditCueDialog))
                dialog.text.insert("end", "!")
                assert dialog._draft_history(dialog.text.edit_undo) == "break"
                assert dialog.text.get("1.0", "end-1c") == "Hello world"
                dialog.text.insert("end", ".")
                exit_answers.append(tv.confirm_unsaved_before_exit())
                dialog.ok()

            viewer.after(30, edit_draft)
            viewer._edit_cue_text(0)
            assert exit_answers == [False]
            assert viewer.segments[0]["text"] == "Hello world."
            viewer._refresh_history_menu()
            assert viewer._edit_menu.entrycget(0, "label") == "Undo Edit cue text"
            viewer._edit_menu.invoke(0)
            assert viewer.segments[0]["text"] == "Hello world"

            timestamp = tv.EditTimestampDialog(viewer, 0)
            timestamp.start_var.set("0.25")
            timestamp._save()
            assert viewer.segments[0]["start"] == 0.25
            viewer._undo_edit()
            assert viewer.segments[0]["start"] == 0

            def set_split():
                dialog = next(child for child in viewer.winfo_children() if isinstance(child, tv.SplitCueDialog))
                dialog.fields[0].mark_set("insert", "1.5")
                dialog.ok()

            viewer.after(30, set_split)
            viewer._open_split_cue(0)
            assert [cue["text"] for cue in viewer.segments[:2]] == ["Hello", "world"]
            viewer._join_next(0)
            assert viewer.segments[0]["text"] == "Hello world"

            seeks = []
            viewer._seek_to = seeks.append
            viewer._reading_enabled.set(True)
            viewer._toggle_reading()
            rendered = viewer._reading_text.get("1.0", "end")
            assert "سلام" in rendered and "你好。" in rendered
            assert viewer._reading_text.tag_cget("paragraph_1", "justify") == "right"
            viewer._reading_text.mark_set("insert", viewer._reading_text.tag_ranges("paragraph_1")[0])
            viewer._seek_reading_caret(None)
            assert seeks[-1] == 5
            with monkeypatch.context() as patch:
                patch.setattr(viewer, "focus_get", lambda: viewer._reading_text)
                assert viewer._history_shortcut(viewer._undo_edit) == "break"
            assert len(viewer.segments) == 4
            viewer._redo_edit()

            viewer._apply_cue_text(0, "Unsaved original", "Edit cue text")
            history.record_transcript_comparison(str(original), str(result))
            tv.show_transcript_comparison(root, str(original), str(result), history)
            compare = next(child for child in root.winfo_children() if isinstance(child, tv.TranscriptComparison))
            assert "Unsaved original" in compare.texts[0].get("1.0", "end")
            assert "Different wording" in compare.texts[1].get("1.0", "end")
            prefer_new = next(child for frame in compare.winfo_children() for child in frame.winfo_children()
                              if isinstance(child, ttk.Radiobutton) and child.cget("text") == "Prefer new")
            prefer_new.invoke()
            assert history.transcript_comparison_for(str(original))[2] == str(result)
            assert "Unsaved original" not in original.read_text(encoding="utf-8")
            assert viewer._dirty
        finally:
            viewer._dirty = False
            viewer.destroy()
            root.destroy()


def test_rerun_refuses_moved_original_even_if_playback_finds_a_neighbor(tmp_path, monkeypatch):
    transcript = tmp_path / "sample.json"
    transcript.write_text('[{"start":0,"end":1,"text":"original"}]', encoding="utf-8")
    neighboring_media = tmp_path / "sample.mp3"
    neighboring_media.touch()
    missing_media = str(tmp_path / "elsewhere" / "sample.mp3")
    errors = []
    monkeypatch.setattr(tv, "_try_load_vlc", lambda: (None, ""))
    monkeypatch.setattr(tv, "show_error", lambda *a, **k: errors.append(a))
    monkeypatch.setattr(tv, "ComparisonPresetDialog", lambda *a: pytest.fail("opened for the wrong media"))
    root = tk.Tk()
    root.withdraw()
    try:
        viewer = tv.open_viewer(root, str(transcript), media_path=missing_media)
        assert viewer.media_path == str(neighboring_media)
        viewer._transcribe_again()
        assert errors
    finally:
        root.destroy()
