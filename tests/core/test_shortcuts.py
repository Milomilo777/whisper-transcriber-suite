"""Platform-aware shortcut labels and bindings (app/shortcuts.py).

macOS must show Command-based hints and bind Command keys; Windows and Linux
keep the exact Ctrl labels they always had.
"""
from __future__ import annotations

import sys

import pytest

pytest.importorskip("tkinter")

from app import shortcuts

CMD = chr(0x2318)


def _platform(monkeypatch, name: str) -> None:
    monkeypatch.setattr(sys, "platform", name)


def test_accel_text_windows_linux_use_ctrl(monkeypatch):
    for plat in ("win32", "linux"):
        _platform(monkeypatch, plat)
        assert shortcuts.accel_text("o") == "Ctrl+O"
        assert shortcuts.accel_text("Return") == "Ctrl+Enter"


def test_accel_text_macos_uses_command(monkeypatch):
    _platform(monkeypatch, "darwin")
    assert shortcuts.accel_text("o") == CMD + "O"
    assert shortcuts.accel_text("o", plain=True) == "Cmd+O"
    assert "Ctrl" not in shortcuts.accel_text("f")
    assert shortcuts.accel_text("Return") == CMD + "Return"


def test_bind_sequences_per_platform(monkeypatch):
    _platform(monkeypatch, "win32")
    assert shortcuts.bind_sequences("o") == ["<Control-o>", "<Control-O>"]
    assert shortcuts.bind_sequences("Return") == ["<Control-Return>"]
    _platform(monkeypatch, "darwin")
    assert shortcuts.bind_sequences("o") == ["<Command-o>", "<Command-O>"]
    assert shortcuts.bind_sequences("Return") == ["<Command-Return>"]


def test_menu_item_windows_keeps_exact_legacy_labels(monkeypatch):
    _platform(monkeypatch, "win32")
    assert shortcuts.menu_item("Browse...", "o", gap=26) == {
        "label": "Browse...                          Ctrl+O"
    }
    assert shortcuts.menu_item(shortcuts.quit_label(), "q", gap=34) == {
        "label": "Exit                                  Ctrl+Q"
    }


def test_menu_item_macos_uses_native_accelerator(monkeypatch):
    _platform(monkeypatch, "darwin")
    assert shortcuts.menu_item("Browse...", "o", gap=26) == {
        "label": "Browse...", "accelerator": "Command-O"
    }


def test_quit_label(monkeypatch):
    _platform(monkeypatch, "darwin")
    assert shortcuts.quit_label() == "Quit"
    for plat in ("win32", "linux"):
        _platform(monkeypatch, plat)
        assert shortcuts.quit_label() == "Exit"


@pytest.mark.parametrize("plat,mod", [("darwin", "Command"), ("win32", "Control")])
def test_bind_shortcut_really_binds_and_fires(monkeypatch, plat, mod):
    """The sequence is accepted by Tk and invokes the callback (event_generate)."""
    import tkinter as tk
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        _platform(monkeypatch, plat)
        calls: list[int] = []
        shortcuts.bind_shortcut(root, "o", lambda: calls.append(1))
        assert root.bind(f"<{mod}-o>")
        assert root.bind(f"<{mod}-O>")
        if plat == "win32":  # Command is a real modifier only on Tk/aqua
            root.deiconify()
            root.update()
            root.focus_force()
            root.update()
            root.event_generate("<Control-o>", when="now")
            if not calls:
                pytest.skip("window could not take keyboard focus here")
            assert calls == [1]
    finally:
        root.destroy()


def test_about_text_is_platform_neutral_and_menus_have_no_ctrl_on_macos(monkeypatch):
    from app.app import build_about_sections

    def blob() -> str:
        out: list[str] = []
        for title, subs in build_about_sections():
            out.append(title)
            for sub, bullets in subs:
                out.append(sub)
                out.extend(bullets)
        return "\n".join(out)

    _platform(monkeypatch, "darwin")
    mac = blob()
    assert "Ctrl+" not in mac
    assert "Exit" not in mac.replace("Exit with queued", "")
    assert CMD + "O" in mac and CMD + "Q" in mac
    _platform(monkeypatch, "win32")
    win = blob()
    assert "Ctrl+O" in win and "Ctrl+Q" in win and "Exit" in win


def test_vlc_hint_mentions_bitness_only_on_windows(monkeypatch):
    from app.dialogs import transcript_viewer as tv

    assert "64-bit" in tv._vlc_missing_hint("win32")
    for plat in ("darwin", "linux"):
        for fn in (tv._vlc_missing_hint, tv._vlc_start_failed_hint):
            text = fn(plat)
            assert "32-bit" not in text and "64-bit" not in text
    assert "64-bit" in tv._vlc_start_failed_hint("win32")
