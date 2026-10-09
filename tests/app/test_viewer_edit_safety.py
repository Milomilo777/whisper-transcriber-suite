"""Transcript viewer: edits reach the subtitle files, never get lost, never delete real words.

Covers the fillers (per language, whole words, punctuation kept), Save keeping the
SRT/VTT/ASS next to the JSON in step (and leaving files edited elsewhere alone), the
"Open in Subtitle Edit" button with unsaved edits or no subtitle file, one viewer per
JSON, a JSON changed on disk after loading, non-string segment fields, and Replace
changing only the selected occurrence.
"""
from __future__ import annotations

import json
import os
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")

from app.dialogs import transcript_viewer as tv  # noqa: E402
from core import subtitle_edit as se  # noqa: E402


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
        {"start": 0.0, "end": 1.25, "text": "Hello world"},
        {"start": 1.25, "end": 3.5, "text": "Second line here"},
    ]


def _write_outputs(tmp_path, formats: list[str]) -> str:
    """The transcriber's own writer, so the files match what a real run leaves."""
    from core.transcriber import _write_outputs as write_outputs

    base = str(tmp_path / "talk")
    written = write_outputs(base, _segments(), str(tmp_path / "talk.mp4"), formats)
    return next(p for p in written if p.endswith(".json"))


def _open(root, json_path: str, **kwargs: Any) -> tv.TranscriptViewer:
    viewer = tv.TranscriptViewer(root, json_path, **kwargs)
    viewer.withdraw()
    viewer._finish_exports()  # the open-time check of the exports runs in a worker
    return viewer


def _close(viewer: tv.TranscriptViewer) -> None:
    viewer._dirty = False
    viewer._on_close()


def _edit_first_segment(viewer: tv.TranscriptViewer, text: str) -> None:
    tv._set_segment_text(viewer.segments[0], text)
    viewer._dirty = True


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()


# --- Remove fillers ------------------------------------------------------------


@pytest.mark.parametrize(("language", "text"), [
    ("de", "Er ist müde."),
    ("nl", "Het is er niet."),
    ("da", "Han er her."),
    ("no", "Det er bra."),
    ("en", "Mm-hmm, uh-huh."),
    ("en", "The eraser is here."),
    ("en", "Write to user@um.com today."),
    ("en", "Play um.mp3 now."),
    ("en", "See um/er.txt here."),
])
def test_fillers_keep_real_words(language: str, text: str) -> None:
    pattern = tv._filler_regex(tv._filler_words_for(language))
    assert tv._strip_fillers(text, pattern) == text


@pytest.mark.parametrize(("language", "text", "expected"), [
    ("en", "Hello um, world", "Hello, world"),
    ("en", "Hello, um, world", "Hello, world"),
    ("en", "Hello um. Bye", "Hello. Bye"),
    ("en", "Hello, um.", "Hello."),
    ("en", "Um, so we start.", "so we start."),
    ("en", "Are you uh sure?", "Are you sure?"),
    ("de", "Ich äh weiß es nicht.", "Ich weiß es nicht."),
    ("fr", "Je pense, euh, que oui.", "Je pense, que oui."),
    # Punctuation around the filler (reviewer round 1).
    ("en", '"Um, hello"', '"hello"'),
    ("en", "Hello. Um, world", "Hello. world"),
    ("en", "(um) hello", "hello"),
    ("en", "so - um - then", "so - then"),
    ("en", 'Hello, "um," world', "Hello, world"),
    ("en", '"yes", "um, no"', '"yes", "no"'),
    ("en", '"yes", "um"', '"yes",'),
    # Marks the text itself opens with stay; only marks the filler exposed go.
    ("en", "... um, well", "... well"),
    ("en", "...and then um we go", "...and then we go"),
    ("en", "?! um what", "?! what"),
    ("en", "Um. So", "So"),
])
def test_fillers_are_removed_with_punctuation_kept(language: str, text: str, expected: str) -> None:
    pattern = tv._filler_regex(tv._filler_words_for(language))
    assert tv._strip_fillers(text, pattern) == expected


@pytest.mark.parametrize("language", [None, "", "auto", "fa", "xx"])
def test_no_filler_list_for_unknown_languages(language: str | None) -> None:
    assert tv._filler_words_for(language) == ()


@pytest.mark.parametrize("language", ["en", "EN", "en-US", "en_GB", "English"])
def test_language_spellings_find_the_list(language: str) -> None:
    assert "um" in tv._filler_words_for(language)


def test_viewer_without_language_removes_nothing(root, tmp_path, notices, monkeypatch) -> None:
    path = tmp_path / "de.json"
    path.write_text(json.dumps([{"start": 0, "end": 1, "text": "Er ist um da."}]), encoding="utf-8")
    asked: list[Any] = []
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: asked.append(a) or True)
    viewer = _open(root, str(path))
    try:
        viewer._remove_fillers()
        assert viewer.segments[0]["text"] == "Er ist um da."
        assert viewer._dirty is False and asked == []
        assert notices[-1][1] == "warning" and "language" in notices[-1][0]
    finally:
        _close(viewer)


def test_german_viewer_removes_aeh_but_not_er(root, tmp_path, notices, monkeypatch) -> None:
    path = tmp_path / "de.json"
    path.write_text(json.dumps([{"start": 0, "end": 1, "text": "Er ist äh müde."}]), encoding="utf-8")
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: True)
    viewer = _open(root, str(path), language="de")
    try:
        viewer._remove_fillers()
        assert viewer.segments[0]["text"] == "Er ist müde."
    finally:
        _close(viewer)


# --- Save keeps the subtitle files in step -------------------------------------


def test_save_rewrites_the_matching_subtitle_files(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "vtt", "ass", "json"])
    viewer = _open(root, json_path)
    try:
        assert len(viewer._synced_siblings) == 3
        _edit_first_segment(viewer, "Edited in the viewer")
        viewer._save_changes()
        viewer._finish_exports()
        for ext in ("srt", "vtt", "ass"):
            body = _read(str(tmp_path / f"talk.{ext}"))
            assert "Edited in the viewer" in body and "Hello world" not in body
        assert notices[-1][1] == "success" and "talk.srt" in notices[-1][0]
        # A second save keeps them in step too.
        _edit_first_segment(viewer, "Edited twice")
        viewer._save_changes()
        viewer._finish_exports()
        assert "Edited twice" in _read(str(tmp_path / "talk.srt"))
    finally:
        _close(viewer)


def test_save_leaves_a_subtitle_file_edited_elsewhere_alone(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "vtt", "json"])
    srt = str(tmp_path / "talk.srt")
    viewer = _open(root, json_path)
    try:
        # Subtitle Edit saves the SRT while the viewer is open.
        hand_edit = _read(srt).replace("Hello world", "Fixed in Subtitle Edit")
        with open(srt, "w", encoding="utf-8", newline="\n") as f:
            f.write(hand_edit)
        os.utime(srt, ns=(os.stat(srt).st_atime_ns, os.stat(srt).st_mtime_ns + 5_000_000))
        _edit_first_segment(viewer, "Edited in the viewer")
        viewer._save_changes()
        viewer._finish_exports()
        assert _read(srt) == hand_edit
        assert "Edited in the viewer" in _read(str(tmp_path / "talk.vtt"))
        assert any(kind == "warning" and "talk.srt" in text for text, kind in notices)
    finally:
        _close(viewer)


def test_subtitle_file_that_differs_at_load_is_not_rewritten(root, tmp_path, notices) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    srt = str(tmp_path / "talk.srt")
    hand_edit = _read(srt).replace("Second line here", "Edited before opening")
    with open(srt, "w", encoding="utf-8", newline="\n") as f:
        f.write(hand_edit)
    viewer = _open(root, json_path)
    try:
        assert viewer._synced_siblings == {}
        _edit_first_segment(viewer, "Viewer edit")
        viewer._save_changes()
        viewer._finish_exports()
        assert _read(srt) == hand_edit
    finally:
        _close(viewer)


def test_crlf_and_bom_subtitle_files_still_count_as_matching(root, tmp_path) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    srt = str(tmp_path / "talk.srt")
    body = _read(srt)
    with open(srt, "wb") as f:
        f.write(b"\xef\xbb\xbf" + body.replace("\n", "\r\n").encode("utf-8"))
    viewer = _open(root, json_path)
    try:
        assert list(viewer._synced_siblings) == [srt]
    finally:
        _close(viewer)


# --- Open in Subtitle Edit -------------------------------------------------------


@pytest.fixture
def se_calls(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    got: list[Any] = []
    monkeypatch.setattr(tv.subtitle_edit_ui, "open_in_subtitle_edit",
                        lambda parent, cfg, path: got.append(path))
    monkeypatch.setattr(se, "find_subtitle_edit", lambda *a, **k: r"C:\SE\SubtitleEdit.exe")
    return got


def test_subtitle_edit_after_yes_shows_the_unsaved_edits(root, tmp_path, notices, se_calls, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    monkeypatch.setattr(tv.messagebox, "askyesnocancel", lambda *a, **k: True)
    viewer = _open(root, json_path)
    try:
        _edit_first_segment(viewer, "Unsaved edit")
        viewer._open_in_subtitle_edit()
        assert se_calls == [str(tmp_path / "talk.srt")]
        assert "Unsaved edit" in _read(se_calls[0])
        assert viewer._dirty is False
    finally:
        _close(viewer)


def test_subtitle_edit_cancel_opens_nothing(root, tmp_path, notices, se_calls, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    monkeypatch.setattr(tv.messagebox, "askyesnocancel", lambda *a, **k: None)
    viewer = _open(root, json_path)
    try:
        _edit_first_segment(viewer, "Unsaved edit")
        viewer._open_in_subtitle_edit()
        assert se_calls == [] and viewer._dirty is True
    finally:
        _close(viewer)


def test_subtitle_edit_no_opens_the_saved_version(root, tmp_path, notices, se_calls, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["srt", "json"])
    monkeypatch.setattr(tv.messagebox, "askyesnocancel", lambda *a, **k: False)
    viewer = _open(root, json_path)
    try:
        _edit_first_segment(viewer, "Unsaved edit")
        viewer._open_in_subtitle_edit()
        assert "Hello world" in _read(se_calls[0]) and viewer._dirty is True
    finally:
        _close(viewer)


def test_json_only_output_gets_an_srt_for_subtitle_edit(root, tmp_path, notices, se_calls, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["json"])
    monkeypatch.setattr(tv.messagebox, "askyesnocancel", lambda *a, **k: False)
    viewer = _open(root, json_path)
    try:
        _edit_first_segment(viewer, "Unsaved edit")
        viewer._open_in_subtitle_edit()
        srt = str(tmp_path / "talk.srt")
        assert se_calls == [srt]
        # "No" = the saved version: the export comes from the JSON on disk.
        assert "Hello world" in _read(srt) and "Unsaved edit" not in _read(srt)
        # The export matches the JSON, so the next Save keeps it in step.
        viewer._save_changes()
        viewer._finish_exports()
        assert "Unsaved edit" in _read(srt)
    finally:
        _close(viewer)


def test_no_export_when_subtitle_edit_is_missing(root, tmp_path, notices, monkeypatch) -> None:
    got: list[Any] = []
    monkeypatch.setattr(tv.subtitle_edit_ui, "open_in_subtitle_edit",
                        lambda parent, cfg, path: got.append(path))
    monkeypatch.setattr(se, "find_subtitle_edit", lambda *a, **k: None)
    json_path = _write_outputs(tmp_path, ["json"])
    viewer = _open(root, json_path)
    try:
        viewer._open_in_subtitle_edit()
        assert got == [None] and not (tmp_path / "talk.srt").exists()
    finally:
        _close(viewer)


# --- one viewer per JSON, file changed on disk --------------------------------------


def test_second_open_focuses_the_open_viewer(root, tmp_path) -> None:
    json_path = _write_outputs(tmp_path, ["json"])
    first = tv.open_viewer(root, json_path)
    assert first is not None
    try:
        first.withdraw()
        other_spelling = os.path.join(str(tmp_path), ".", os.path.basename(json_path))
        if os.name == "nt":
            other_spelling = other_spelling.upper()
        assert tv.open_viewer(root, other_spelling) is first
    finally:
        _close(first)
    second = tv.open_viewer(root, json_path)
    assert second is not None and second is not first
    _close(second)


def test_viewer_leaves_the_registry_when_its_parent_goes(tmp_path) -> None:
    json_path = _write_outputs(tmp_path, ["json"])
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    viewer = tv.open_viewer(r, json_path)
    assert viewer is not None and tv._viewer_key(json_path) in tv._OPEN_VIEWERS
    r.destroy()
    assert tv._viewer_key(json_path) not in tv._OPEN_VIEWERS


def test_a_viewer_that_failed_to_build_is_not_reused(root, tmp_path, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["json"])

    def broken(_self: Any) -> None:
        raise RuntimeError("build failed")

    with monkeypatch.context() as m:
        m.setattr(tv.TranscriptViewer, "_populate_listbox", broken)
        with pytest.raises(RuntimeError):
            tv.open_viewer(root, json_path)
    assert tv._viewer_key(json_path) not in tv._OPEN_VIEWERS
    viewer = tv.open_viewer(root, json_path)
    assert viewer is not None and len(viewer.tree.get_children()) == 2
    _close(viewer)


@pytest.mark.parametrize("overwrite", [False, True])
def test_save_asks_before_overwriting_a_file_changed_on_disk(
    root, tmp_path, notices, monkeypatch, overwrite: bool,
) -> None:
    json_path = _write_outputs(tmp_path, ["json"])
    viewer = _open(root, json_path)
    try:
        other = json.dumps([{"start": 0, "end": 1, "text": "Written by another program"}])
        with open(json_path, "w", encoding="utf-8") as f:
            f.write(other)
        asked: list[Any] = []
        monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: asked.append(a) or overwrite)
        _edit_first_segment(viewer, "Viewer edit")
        viewer._save_changes()
        viewer._finish_exports()
        assert len(asked) == 1
        assert ("Viewer edit" in _read(json_path)) is overwrite
        assert viewer._dirty is (not overwrite)
    finally:
        _close(viewer)


def test_save_without_outside_change_does_not_ask(root, tmp_path, notices, monkeypatch) -> None:
    json_path = _write_outputs(tmp_path, ["json"])
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: pytest.fail("asked"))
    viewer = _open(root, json_path)
    try:
        for text in ("First save", "Second save"):
            _edit_first_segment(viewer, text)
            viewer._save_changes()
            viewer._finish_exports()
            assert text in _read(json_path)
    finally:
        _close(viewer)


# --- odd JSON ----------------------------------------------------------------------


def test_non_string_fields_do_not_crash_the_viewer(root, tmp_path) -> None:
    path = tmp_path / "odd.json"
    path.write_text(json.dumps([
        {"start": 0, "end": 1, "text": 5, "speaker": 7, "words": 3},
        {"start": 1, "end": 2, "text": ["a"], "speaker": {"x": 1}},
    ]), encoding="utf-8")
    viewer = _open(root, str(path))
    try:
        rows = viewer.tree.get_children()
        assert viewer.tree.item(rows[0], "values")[1:] == ("7", "5")
        assert viewer.tree.item(rows[1], "values")[2] == ""
        viewer._update_karaoke(0.5)
    finally:
        _close(viewer)


def test_json_with_a_bom_loads(root, tmp_path) -> None:
    path = tmp_path / "bom.json"
    path.write_bytes(b"\xef\xbb\xbf" + json.dumps(_segments()).encode("utf-8"))
    viewer = _open(root, str(path))
    try:
        assert len(viewer.segments) == 2
    finally:
        _close(viewer)


# --- Find and replace ------------------------------------------------------------------


def _dialog(root, tmp_path, texts: list[str]) -> tuple[tv.TranscriptViewer, tv.FindReplaceDialog]:
    path = tmp_path / "fr.json"
    path.write_text(json.dumps(
        [{"start": i, "end": i + 1, "text": t} for i, t in enumerate(texts)]
    ), encoding="utf-8")
    viewer = _open(root, str(path))
    dlg = tv.FindReplaceDialog(viewer)
    dlg.withdraw()
    return viewer, dlg


def test_replace_changes_only_the_selected_occurrence(root, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer, dlg = _dialog(root, tmp_path, ["a cat and a cat", "one more cat"])
    try:
        dlg.find_var.set("cat")
        dlg.replace_var.set("dog")
        assert dlg.find_next() and (dlg.last_match_idx, dlg.last_match_pos) == (0, 2)
        dlg.replace_current()
        assert viewer.segments[0]["text"] == "a dog and a cat"
        assert (dlg.last_match_idx, dlg.last_match_pos) == (0, 12)
        dlg.replace_current()
        assert viewer.segments[0]["text"] == "a dog and a dog"
        assert (dlg.last_match_idx, dlg.last_match_pos) == (1, 9)
        assert viewer.segments[1]["text"] == "one more cat"
    finally:
        dlg.destroy()
        _close(viewer)


def test_a_new_search_word_forgets_the_old_match(root, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer, dlg = _dialog(root, tmp_path, ["cat and cab", "the cab"])
    try:
        dlg.find_var.set("cab")
        dlg.find_next()  # selects "cab" at position 8
        dlg.find_var.set("ca")
        dlg.replace_var.set("X")
        dlg.replace_current()  # finds "ca" first, then replaces that one
        assert viewer.segments[0]["text"] == "Xt and cab"
    finally:
        dlg.destroy()
        _close(viewer)


def test_replace_with_text_containing_the_needle_moves_on(root, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer, dlg = _dialog(root, tmp_path, ["cat cat"])
    try:
        dlg.find_var.set("cat")
        dlg.replace_var.set("cats")
        dlg.find_next()
        dlg.replace_current()
        assert viewer.segments[0]["text"] == "cats cat"
        assert dlg.last_match_pos == 5
    finally:
        dlg.destroy()
        _close(viewer)


def test_find_next_shows_a_row_hidden_by_the_search_filter(root, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer, dlg = _dialog(root, tmp_path, ["alpha", "beta target"])
    try:
        viewer.search_var.set("alpha")
        assert not viewer.tree.exists("1")
        dlg.find_var.set("target")
        assert dlg.find_next()
        assert viewer.tree.exists("1") and viewer.tree.selection() == ("1",)
    finally:
        dlg.destroy()
        _close(viewer)


# --- The caption under the player follows edits ------------------------------------------


def _caption(viewer: tv.TranscriptViewer) -> str:
    return str(viewer._words_lbl.cget("text"))


def test_replace_all_refreshes_the_caption_of_the_active_segment(root, tmp_path, monkeypatch) -> None:
    """The caption kept "fox" after Replace all had changed the segment to "cat"."""
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer, dlg = _dialog(root, tmp_path, ["Hello there", "The quick brown fox jumps"])
    try:
        viewer._set_active_segment(1)
        assert _caption(viewer) == "The quick brown fox jumps"
        dlg.find_var.set("fox")
        dlg.replace_var.set("cat")
        dlg.replace_all()
        assert viewer.segments[1]["text"] == "The quick brown cat jumps"
        assert _caption(viewer) == "The quick brown cat jumps"
    finally:
        dlg.destroy()
        _close(viewer)


def test_replace_one_refreshes_the_caption(root, tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(tv.messagebox, "showinfo", lambda *a, **k: None)
    viewer, dlg = _dialog(root, tmp_path, ["The quick brown fox"])
    try:
        viewer._set_active_segment(0)
        dlg.find_var.set("fox")
        dlg.replace_var.set("cat")
        assert dlg.find_next()
        dlg.replace_current()
        assert _caption(viewer) == "The quick brown cat"
    finally:
        dlg.destroy()
        _close(viewer)


def test_remove_fillers_refreshes_the_caption(root, tmp_path, monkeypatch, notices) -> None:
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *a, **k: True)
    path = tmp_path / "f.json"
    path.write_text(json.dumps([{"start": 0, "end": 2, "text": "Well, um, hello"}]), encoding="utf-8")
    viewer = _open(root, str(path), language="en")
    try:
        viewer._set_active_segment(0)
        assert _caption(viewer) == "Well, um, hello"
        viewer._remove_fillers()
        assert _caption(viewer) == viewer.segments[0]["text"] != "Well, um, hello"
    finally:
        _close(viewer)


def test_the_caption_is_cleared_when_no_segment_is_active(root, tmp_path) -> None:
    viewer, dlg = _dialog(root, tmp_path, ["one", "two"])
    try:
        viewer._set_active_segment(1)
        viewer._active_segment_idx = 5  # out of range, e.g. after the list changed
        viewer._populate_listbox()
        assert viewer._active_segment_idx is None and _caption(viewer) == ""
    finally:
        dlg.destroy()
        _close(viewer)
