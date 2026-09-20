"""Tests for ``app/widgets/console.py`` — the log Text widget + its menu.

The menu is per-console: an earlier revision built a brand-new ``tk.Menu``
inside the right-click handler, and Tk only destroys such a child with its
parent Text widget, so every right-click leaked one orphaned menu widget
under the log. ``test_popup_reuses_the_same_menu`` pins the fix.
"""
from __future__ import annotations

import types

import pytest

tk = pytest.importorskip("tkinter")

from app.widgets import console as console_mod  # noqa: E402


@pytest.fixture
def root():
    r = tk.Tk()
    r.withdraw()
    try:
        yield r
    finally:
        try:
            r.destroy()
        except tk.TclError:
            pass


def _menus(txt: tk.Text) -> list[tk.Menu]:
    return [c for c in txt.winfo_children() if isinstance(c, tk.Menu)]


def test_build_console_creates_exactly_one_menu(root):
    txt = console_mod.build_console(root, theme="dark")
    assert len(_menus(txt)) == 1


def test_popup_reuses_the_same_menu(root, monkeypatch):
    """Repeated right-clicks must post the one menu, not build new ones."""
    txt = console_mod.build_console(root, theme="dark")
    menu = _menus(txt)[0]

    posted: list[tuple[int, int]] = []
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda self, x, y: posted.append((x, y)))

    event = types.SimpleNamespace(x_root=10, y_root=20)
    for _ in range(5):
        assert console_mod._popup_console_menu(menu, event) == "break"

    assert posted == [(10, 20)] * 5
    # Still the same single child — no per-click menu accumulation.
    assert _menus(txt) == [menu]


def test_clear_restores_a_disabled_state(root):
    """Clear must flip to normal, delete, then restore `disabled`.

    Without the restore the log would be left permanently editable —
    the documented past bug this guards.
    """
    txt = console_mod.build_console(root, theme="dark")
    console_mod.insert_log_line(txt, "hello")
    txt.configure(state="disabled")

    _menus(txt)[0].invoke(3)  # Copy, Copy all, separator, Clear

    assert txt.get("1.0", "end-1c") == ""
    assert str(txt.cget("state")) == "disabled"


def test_clear_leaves_an_enabled_widget_enabled(root):
    txt = console_mod.build_console(root, theme="dark")
    console_mod.insert_log_line(txt, "hello")

    _menus(txt)[0].invoke(3)

    assert txt.get("1.0", "end-1c") == ""
    assert str(txt.cget("state")) == "normal"


def test_error_keywords_are_tagged_but_filenames_are_not(root):
    txt = console_mod.build_console(root, theme="dark")
    console_mod.insert_log_line(txt, "Saved C:/clips/my_failsafe_video.mp4")
    console_mod.insert_log_line(txt, "Could not open the file")

    assert "error" not in txt.tag_names("1.0")
    assert "error" in txt.tag_names("2.0")
