"""The subtitles-or-transcribe question window, driven on a real (hidden) Tk root."""
from __future__ import annotations

import pytest

from app.dialogs import caption_choice as cc


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


def _click(root, button_text: str, *, tick_dont_ask: bool = False, closing: bool = False) -> None:
    """Once the modal window is up, act on it from the Tk event loop."""
    from tkinter import ttk

    def act() -> None:
        dialogs = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
        assert len(dialogs) == 1
        dialog = dialogs[0]
        if tick_dont_ask:
            next(w for w in _widgets(dialog) if isinstance(w, ttk.Checkbutton)).invoke()
        if closing:
            dialog.destroy()
            return
        button = next(
            w for w in _widgets(dialog)
            if isinstance(w, ttk.Button) and str(w.cget("text")) == button_text
        )
        button.invoke()

    root.after(50, act)


def test_use_the_subtitles(tk_root):
    _click(tk_root, "Use the subtitles")
    assert cc.ask_caption_choice(tk_root, kind="manual", language="English") == (
        cc.CHOICE_CAPTIONS, False,
    )


def test_transcribe_with_dont_ask_again(tk_root):
    _click(tk_root, "Transcribe", tick_dont_ask=True)
    assert cc.ask_caption_choice(tk_root, kind="auto", language="English") == (
        cc.CHOICE_TRANSCRIBE, True,
    )


def test_closing_the_window_cancels_and_never_remembers(tk_root):
    _click(tk_root, "", tick_dont_ask=True, closing=True)
    assert cc.ask_caption_choice(tk_root, kind="manual", language="English") == (
        cc.CHOICE_CANCEL, False,
    )


def test_the_window_names_the_language_and_the_kind(tk_root):
    from tkinter import ttk

    seen: list[str] = []

    def look() -> None:
        dialog = next(w for w in tk_root.winfo_children() if w.winfo_class() == "Toplevel")
        seen.extend(str(w.cget("text")) for w in _widgets(dialog) if isinstance(w, ttk.Label))
        next(
            w for w in _widgets(dialog)
            if isinstance(w, ttk.Button) and str(w.cget("text")) == "Transcribe"
        ).invoke()

    tk_root.after(50, look)
    cc.ask_caption_choice(tk_root, kind="auto", language="Spanish")
    joined = " ".join(seen)
    assert "Spanish subtitles (automatic)" in joined
    assert "less accurate" in joined
    assert "Use the existing subtitles (seconds) or transcribe (minutes)?" in joined


@pytest.mark.parametrize(
    ("saved", "expected"),
    [
        ({}, "ask"),
        ({"download_caption_choice": "captions"}, "captions"),
        ({"download_caption_choice": "transcribe"}, "transcribe"),
        ({"download_caption_choice": "cancel"}, "ask"),
        ({"download_caption_choice": None}, "ask"),
    ],
)
def test_remembered_choice(saved, expected):
    assert cc.remembered_choice(saved) == expected
