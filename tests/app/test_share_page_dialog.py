"""The "Save shareable page" question window and save flow, on a real (hidden) Tk root."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.dialogs import share_page as sp


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    root = tk.Tk()
    root.withdraw()
    try:
        yield root
    finally:
        try:
            root.destroy()
        except tk.TclError:
            pass


def _widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _widgets(child)


def _act(root, button_text: str | None, *, untick_footer: bool = False, seen: list | None = None):
    from tkinter import ttk

    def act() -> None:
        dialogs = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
        assert len(dialogs) == 1
        dialog = dialogs[0]
        if seen is not None:
            seen.extend(str(w.cget("text")) for w in _widgets(dialog) if isinstance(w, ttk.Label))
        if untick_footer:
            next(w for w in _widgets(dialog) if isinstance(w, ttk.Checkbutton)).invoke()
        if button_text is None:
            dialog.destroy()
            return
        next(w for w in _widgets(dialog)
             if isinstance(w, ttk.Button) and str(w.cget("text")) == button_text).invoke()

    root.after(50, act)


SEGS = [{"start": 0.0, "end": 1.0, "text": "hello world", "speaker": "Speaker 1"}]


def test_save_writes_the_page_with_the_footer(tk_root, tmp_path, monkeypatch):
    media = tmp_path / "talk.mp3"
    media.write_bytes(b"x")
    out = tmp_path / "talk.html"
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(out))
    opened: list[str] = []
    monkeypatch.setattr(sp, "open_in_browser", lambda path, master: opened.append(path))
    seen: list[str] = []
    _act(tk_root, "Save\u2026", seen=seen)
    path = sp.save_shareable_page(tk_root, segments=SEGS, media_path=str(media),
                                  json_path=str(tmp_path / "talk.json"), language="en")
    assert path == str(out)
    page = out.read_text(encoding="utf-8")
    assert 'src="talk.mp3"' in page and "made with Whisper Transcriber Suite" in page
    assert '<html lang="en">' in page
    assert opened == []
    note = " ".join(seen)
    assert "full transcript text" in note and "talk.mp3" in note


def test_save_and_open_without_footer(tk_root, tmp_path, monkeypatch):
    out = tmp_path / "t.html"
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(out))
    opened: list[str] = []
    monkeypatch.setattr(sp, "open_in_browser", lambda path, master: opened.append(path))
    _act(tk_root, "Save and open in browser", untick_footer=True)
    path = sp.save_shareable_page(tk_root, segments=SEGS, media_path=None,
                                  json_path=str(tmp_path / "t.json"))
    assert path == str(out) and opened == [str(out)]
    page = out.read_text(encoding="utf-8")
    assert "Whisper Transcriber Suite" not in page
    assert "<audio" not in page


def test_cancel_and_closed_window_write_nothing(tk_root, tmp_path, monkeypatch):
    def never(**_k):
        raise AssertionError("no file dialog after Cancel")
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", never)
    _act(tk_root, "Cancel")
    assert sp.save_shareable_page(tk_root, segments=SEGS, media_path=None,
                                  json_path=str(tmp_path / "t.json")) is None
    _act(tk_root, None)
    assert sp.save_shareable_page(tk_root, segments=SEGS, media_path=None,
                                  json_path=str(tmp_path / "t.json")) is None
    assert list(tmp_path.iterdir()) == []


def test_cancelled_file_dialog_writes_nothing(tk_root, tmp_path, monkeypatch):
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: "")
    _act(tk_root, "Save\u2026")
    assert sp.save_shareable_page(tk_root, segments=SEGS, media_path=None,
                                  json_path=str(tmp_path / "t.json")) is None
    assert list(tmp_path.iterdir()) == []


def test_empty_transcript_is_refused(tk_root, tmp_path, monkeypatch):
    shown: list[str] = []
    monkeypatch.setattr(sp.messagebox, "showinfo", lambda *a, **_k: shown.append(a[1]))
    assert sp.save_shareable_page(tk_root, segments=[{"text": "  "}], media_path=None,
                                  json_path=str(tmp_path / "t.json")) is None
    assert shown


def test_privacy_note_names_the_contents():
    note = sp.privacy_note("C:/x/My talk.mp4")
    assert "full transcript text" in note and "speaker" in note and "chapter" in note
    assert "My talk.mp4" in note and "together" in note
    assert "no player" in sp.privacy_note(None)


def test_load_transcript_and_chapters(tmp_path):
    path = tmp_path / "a.json"
    path.write_text(json.dumps([{"start": 0, "end": 1, "text": "x"}, 5]), encoding="utf-8")
    assert sp.load_transcript(str(path)) == [{"start": 0, "end": 1, "text": "x"}]
    assert sp.load_chapters(str(path)) == []
    (tmp_path / "a.chapters.json").write_text(json.dumps([{"title": "c", "start": 0}, "x"]),
                                              encoding="utf-8")
    assert sp.load_chapters(str(path)) == [{"title": "c", "start": 0}]
    (tmp_path / "a.chapters.json").write_text("{broken", encoding="utf-8")
    assert sp.load_chapters(str(path)) == []
    bad = tmp_path / "b.json"
    bad.write_text(json.dumps({"api_key": "dummy-credential-A"}), encoding="utf-8")
    with pytest.raises(ValueError):
        sp.load_transcript(str(bad))


def test_viewer_exports_its_in_memory_segments(monkeypatch):
    from app.dialogs import transcript_viewer as tv

    calls: list[dict] = []
    monkeypatch.setattr(sp, "save_shareable_page", lambda master, **kw: calls.append(kw))
    edited = [{"start": 0, "end": 1, "text": "edited, not saved"}]
    viewer = SimpleNamespace(segments=edited, media_path="m.mp3", json_path="t.json",
                             chapters=[{"title": "c"}], language="English")
    tv.TranscriptViewer._save_shareable_page(viewer)  # type: ignore[arg-type]
    assert calls == [{"segments": edited, "media_path": "m.mp3", "json_path": "t.json",
                      "chapters": [{"title": "c"}], "language": "en"}]


def test_last_result_card_reads_the_json_and_sidecar(tmp_path, monkeypatch):
    from app.app import App

    json_path = tmp_path / "a.json"
    json_path.write_text(json.dumps(SEGS), encoding="utf-8")
    (tmp_path / "a.chapters.json").write_text(json.dumps([{"title": "c", "start": 0}]),
                                              encoding="utf-8")
    calls: list[dict] = []
    monkeypatch.setattr(sp, "save_shareable_page", lambda master, **kw: calls.append(kw))
    App._save_shareable_page_for(SimpleNamespace(), "a.mp3", str(json_path), "fa")  # type: ignore[arg-type]
    assert calls == [{"segments": SEGS, "media_path": "a.mp3", "json_path": str(json_path),
                      "chapters": [{"title": "c", "start": 0}], "language": "fa"}]


def test_save_and_open_never_opens_a_non_page_file(tk_root, tmp_path, monkeypatch):
    out = tmp_path / "t.bat"
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(out))
    opened: list[str] = []
    monkeypatch.setattr(sp, "open_in_browser", lambda path, master: opened.append(path))
    _act(tk_root, "Save and open in browser")
    assert sp.save_shareable_page(tk_root, segments=SEGS, media_path=None,
                                  json_path=str(tmp_path / "t.json")) == str(out)
    assert out.is_file() and opened == []


@pytest.mark.parametrize("which", ["json", "media"])
def test_never_saves_over_the_transcript_or_media(tk_root, tmp_path, monkeypatch, which):
    json_path = tmp_path / "t.json"
    json_path.write_text("[]", encoding="utf-8")
    media = tmp_path / "t.mp3"
    media.write_bytes(b"audio")
    target = json_path if which == "json" else media
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(target).upper())
    errors: list[str] = []
    monkeypatch.setattr(sp.messagebox, "showerror", lambda *a, **_k: errors.append(a[1]))
    _act(tk_root, "Save…")
    assert sp.save_shareable_page(tk_root, segments=SEGS, media_path=str(media),
                                  json_path=str(json_path)) is None
    assert errors and json_path.read_text(encoding="utf-8") == "[]"
    assert media.read_bytes() == b"audio"


@pytest.mark.parametrize("which", ["json", "media"])
def test_the_overwrite_guard_does_not_rely_on_normcase(tk_root, tmp_path, monkeypatch, which):
    """macOS folds no case in os.path.normcase yet its volumes ignore case: ask the filesystem."""
    import os
    import posixpath

    json_path = tmp_path / "t.json"
    json_path.write_text("[]", encoding="utf-8")
    media = tmp_path / "t.mp3"
    media.write_bytes(b"audio")
    target = json_path if which == "json" else media
    if not (tmp_path / "T.JSON").exists():
        pytest.skip("case-sensitive volume: a case variant is another file")
    monkeypatch.setattr(os.path, "normcase", posixpath.normcase)
    monkeypatch.setattr(sp.filedialog, "asksaveasfilename", lambda **_k: str(target).upper())
    errors: list[str] = []
    monkeypatch.setattr(sp.messagebox, "showerror", lambda *a, **_k: errors.append(a[1]))
    _act(tk_root, "Save…")
    assert sp.save_shareable_page(tk_root, segments=SEGS, media_path=str(media),
                                  json_path=str(json_path)) is None
    assert errors and json_path.read_text(encoding="utf-8") == "[]"
    assert media.read_bytes() == b"audio"
