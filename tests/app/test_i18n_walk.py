"""tests/app/i18n_walk.py on real Tk widgets, and the pilot dialog built in English and qps-ploc.

These tests need a Tk root (a display); they skip without one.
"""
from __future__ import annotations

import json
import tkinter as tk
from pathlib import Path
from tkinter import ttk

import pytest

from app import i18n
from tests.app.i18n_walk import is_pseudo_marked, untranslated, visible_texts

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "i18n" / "problem_report_texts.json"


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture(autouse=True)
def _english():
    i18n.set_language("en")
    yield
    i18n.set_language("en")


def test_is_pseudo_marked() -> None:
    assert is_pseudo_marked(i18n.pseudo_translate("Save all"))
    assert is_pseudo_marked(i18n.pseudo_translate("A") + " — " + i18n.pseudo_translate("B"))
    assert is_pseudo_marked("0 / 2000")  # no letters
    assert not is_pseudo_marked("Save all")
    assert not is_pseudo_marked("Sent with: " + i18n.pseudo_translate("x"))
    assert not is_pseudo_marked("[Save]")  # brackets alone are not the marker


def test_visible_texts_covers_every_kind_of_widget(root: tk.Tk) -> None:
    win = tk.Toplevel(root)
    win.withdraw()
    win.title("Title")
    tk.Label(win, text="tk label").pack()
    ttk.Label(win, text="ttk label").pack()
    var = tk.StringVar(master=win, value="from a variable")
    ttk.Label(win, textvariable=var).pack()
    ttk.Button(win, text="ttk button").pack()
    tk.Button(win, text="tk button").pack()
    ttk.Checkbutton(win, text="check").pack()
    ttk.Radiobutton(win, text="radio").pack()
    frame = ttk.LabelFrame(win, text="group")
    frame.pack()
    ttk.Label(frame, text="inside").pack()
    menu = tk.Menu(win, tearoff=True)
    menu.add_command(label="Open")
    menu.add_separator()
    menu.add_checkbutton(label="Wrap")
    nb = ttk.Notebook(win)
    nb.add(ttk.Frame(nb), text="First tab")
    nb.pack()
    ttk.Combobox(win, values=["one", "two words"]).pack()
    entry = ttk.Entry(win)
    entry.insert(0, "typed by the person")
    entry.pack()
    text = tk.Text(win)
    text.insert("1.0", "also typed")
    text.pack()
    try:
        texts = [t for _p, t in visible_texts(win)]
        for wanted in ("Title", "tk label", "ttk label", "from a variable", "ttk button", "tk button",
                       "check", "radio", "group", "inside", "Open", "Wrap", "First tab", "one",
                       "two words"):
            assert wanted in texts, wanted
        assert "typed by the person" not in texts and "also typed" not in texts
        assert {t for _p, t in untranslated(win)} == set(texts)
    finally:
        win.destroy()


def _build(root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> tk.Toplevel:
    from app.dialogs import problem_report as dialog
    from core import problem_report as pr
    monkeypatch.setattr(pr, "system_summary", lambda: "Whisper Transcriber Suite 9.9.9 on Windows 10 (AMD64)")
    monkeypatch.setattr(pr, "MAX_CHARS", 50)
    monkeypatch.setattr(dialog, "_take_grab", lambda *_a, **_k: None)
    win = dialog.open_problem_report(root, {"stats_url": ""}, "https://example.invalid/new")
    win.withdraw()
    root.update_idletasks()
    return win


def test_pilot_dialog_english_texts_match_the_capture(root: tk.Tk, monkeypatch: pytest.MonkeyPatch) -> None:
    expected = sorted(t for _w, t in json.loads(FIXTURE.read_text(encoding="utf-8"))["empty"] if t)
    win = _build(root, monkeypatch)
    try:
        assert sorted(t for _p, t in visible_texts(win)) == expected
    finally:
        win.destroy()


def test_pilot_dialog_in_pseudo_locale_has_no_untranslated_text(root: tk.Tk,
                                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    i18n.set_language(i18n.PSEUDO_LOCALE)
    win = _build(root, monkeypatch)
    try:
        assert untranslated(win) == []
        assert len(visible_texts(win)) >= 8
    finally:
        win.destroy()
