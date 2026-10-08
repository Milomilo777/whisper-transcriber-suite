"""The English-only model dialog, driven on a real (hidden) Tk root."""
from __future__ import annotations

import pytest

from app.dialogs import english_only_model as dlg

PROMPT = dlg.EnglishOnlyPrompt(
    model="tiny.en", language="Persian", alternative="small",
    reason="It understands Persian and still keeps up with live speech on this computer.",
    size_text="about 500 MB", downloaded=False,
)


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


def _dialog(root):
    dialogs = [w for w in root.winfo_children() if w.winfo_class() == "Toplevel"]
    assert len(dialogs) == 1
    return dialogs[0]


def _act(root, fn):
    root.after(50, lambda: fn(_dialog(root)))


def _press(text):
    from tkinter import ttk

    def act(dialog):
        next(w for w in _widgets(dialog)
             if isinstance(w, ttk.Button) and str(w.cget("text")) == text).invoke()
    return act


@pytest.mark.parametrize("button,choice", [
    ("Switch to small", dlg.CHOICE_SWITCH),
    ("Choose another model…", dlg.CHOICE_CHOOSE),
    ("Keep tiny.en anyway", dlg.CHOICE_KEEP),
    ("Cancel", dlg.CHOICE_CANCEL),
])
def test_each_button(tk_root, button, choice):
    _act(tk_root, _press(button))
    assert dlg.ask_english_only(tk_root, PROMPT) == choice


def test_closing_the_window_cancels(tk_root):
    _act(tk_root, lambda d: d.destroy())
    assert dlg.ask_english_only(tk_root, PROMPT) == dlg.CHOICE_CANCEL


def test_escape_and_enter_are_bound(tk_root):
    """Escape cancels, Enter presses the focused button (else Switch).

    Synthetic key events need keyboard focus, which an unattended test run
    cannot always take, so this checks the bindings; pressing the keys is
    part of the manual GUI check.
    """
    bound: list[str] = []

    def read(dialog):
        bound.extend(dialog.bind())
        dialog.destroy()

    _act(tk_root, read)
    dlg.ask_english_only(tk_root, PROMPT)
    assert "<Key-Escape>" in bound and "<Key-Return>" in bound


def test_the_text_says_problem_fix_and_cost(tk_root):
    from tkinter import ttk

    seen: list[str] = []

    def read(dialog):
        seen.extend(str(w.cget("text")) for w in _widgets(dialog) if isinstance(w, ttk.Label))
        dialog.destroy()

    _act(tk_root, read)
    dlg.ask_english_only(tk_root, PROMPT)
    text = "\n".join(seen)
    assert "tiny.en understands English only." in text
    assert "Persian speech will come out as wrong English text" in text
    assert "Recommended: small." in text
    assert "about 500 MB" in text


def test_prompt_wording_for_auto_and_downloaded():
    auto = dlg.EnglishOnlyPrompt(model="base.en", language="", alternative="small",
                                 reason="R.", downloaded=True)
    assert auto.problem().startswith("With Auto, any speech that is not English")
    assert auto.recommendation().endswith("Already on this computer.")
    unknown = dlg.EnglishOnlyPrompt(model="x.en", language="German", alternative="small",
                                    reason="R.")
    assert unknown.recommendation().endswith("Needs a one-time download.")
