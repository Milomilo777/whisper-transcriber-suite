"""Tests for ``app/widgets/error_dialog.show_error``.

Tk keeps a single grab per display and does not stack them, so the error
dialog's grab_set() replaced whoever held the grab at the time.
Destroying the dialog used to leave that window (e.g. Advanced settings,
itself modal) non-modal, letting the user open a second copy of it.
``show_error`` now restores the previous grab holder on close.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter")
ttk = pytest.importorskip("tkinter.ttk")

from app.widgets.error_dialog import show_error  # noqa: E402


def _error_dialog(parent: tk.Misc, title: str) -> tk.Toplevel:
    dialogs = [
        w for w in parent.winfo_children()
        if isinstance(w, tk.Toplevel) and w.title() == title
    ]
    assert len(dialogs) == 1, f"expected one error dialog, got {dialogs}"
    return dialogs[0]


def _find_button(widget: tk.Misc, text: str) -> ttk.Button | None:
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button) and child.cget("text") == text:
            return child
        found = _find_button(child, text)
        if found is not None:
            return found
    return None


def _dismiss(dlg: tk.Toplevel) -> None:
    ok = _find_button(dlg, "OK")
    assert ok is not None
    ok.invoke()


def test_shows_the_message_and_a_details_toggle():
    root = tk.Tk()
    root.withdraw()
    try:
        show_error(root, "Save failed", "Could not save your settings.", detail="boom")
        root.update_idletasks()
        dlg = _error_dialog(root, "Save failed")
        assert _find_button(dlg, "OK") is not None
        assert _find_button(dlg, "Show details ▸") is not None
    finally:
        root.destroy()


def test_close_restores_the_parents_modal_grab():
    root = tk.Tk()
    root.withdraw()
    host = tk.Toplevel(root)
    host.withdraw()
    try:
        host.grab_set()
        assert root.grab_current() is host

        show_error(host, "Save failed", "Could not save your settings.")
        root.update_idletasks()
        dlg = _error_dialog(host, "Save failed")
        assert root.grab_current() is dlg  # the dialog took the grab

        _dismiss(dlg)

        # The dialog is gone AND the host is modal again.
        assert not dlg.winfo_exists()
        assert root.grab_current() is host
    finally:
        root.destroy()


def test_close_restores_a_modal_dialog_when_parent_is_the_root():
    """Background error paths pass the App root as parent even while a
    modal dialog (e.g. Advanced settings) is open; that dialog must get
    its grab back when the error is dismissed."""
    root = tk.Tk()
    root.withdraw()
    host = tk.Toplevel(root)
    host.withdraw()
    try:
        host.grab_set()

        show_error(root, "Worker error", "The worker failed.")
        root.update_idletasks()
        dlg = _error_dialog(root, "Worker error")
        assert root.grab_current() is dlg

        _dismiss(dlg)

        assert root.grab_current() is host
    finally:
        root.destroy()


def test_close_does_not_grab_a_parent_that_had_none():
    root = tk.Tk()
    root.withdraw()
    host = tk.Toplevel(root)
    host.withdraw()
    try:
        show_error(host, "Save failed", "Could not save your settings.")
        root.update_idletasks()
        dlg = _error_dialog(host, "Save failed")

        _dismiss(dlg)

        assert root.grab_current() is None
    finally:
        root.destroy()
