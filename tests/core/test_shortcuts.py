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


# ---------------------------------------------------------------------------
# Call sites (real widgets), with shortcuts.is_mac patched
# ---------------------------------------------------------------------------


def _mac(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(shortcuts, "is_mac", lambda: value)


def _walk(widget):
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


@pytest.mark.parametrize("mac", [True, False])
def test_transcript_viewer_binds_and_button_texts(monkeypatch, tmp_path, mac):
    import json
    import tkinter as tk
    from tkinter import ttk

    from app.dialogs import transcript_viewer as tv
    from tests.core.test_transcript_viewer import SAMPLE_SEGMENTS

    _mac(monkeypatch, mac)
    monkeypatch.setattr(tv, "_try_load_vlc", lambda: (None, "no vlc in test"))
    p = tmp_path / "demo.json"
    p.write_text(json.dumps(SAMPLE_SEGMENTS), encoding="utf-8")
    root = tk.Tk()
    root.withdraw()
    try:
        viewer = tv.TranscriptViewer(root, str(p))
        viewer.withdraw()
        try:
            bound = set(viewer.bind())
            # Tk normalises <Command-f> to <Mod1-Key-f>.
            mod, other = ("Mod1", "Control") if mac else ("Control", "Mod1")
            for k in ("f", "s"):
                assert f"<{mod}-Key-{k}>" in bound
                assert f"<{other}-Key-{k}>" not in bound
            texts = [w.cget("text") for w in _walk(viewer) if isinstance(w, ttk.Button)]
            find = next(t for t in texts if t.startswith("Find & Replace"))
            save = next(t for t in texts if t.startswith("Save changes"))
            if mac:
                assert find.endswith(f"({CMD}F)") and save.endswith(f"({CMD}S)")
            else:
                assert find == "Find & Replace  (Ctrl+F)"
                assert save == "Save changes  (Ctrl+S)"
        finally:
            viewer._on_close()
    finally:
        root.destroy()


def _bare_app():
    import tkinter as tk
    from unittest.mock import MagicMock

    from app.app import App

    root = App.__new__(App)
    tk.Tk.__init__(root)
    root.withdraw()
    root.theme_var = tk.StringVar(root, value="light")
    root.app_config = {}
    root.integrations_service = MagicMock()
    return root


def _file_menu_entries(root):
    menu = root.nametowidget(root._menubar.entrycget(root._menubar.index("File"), "menu"))
    out = []
    for i in range(menu.index("end") + 1):
        kind = menu.type(i)
        if kind in ("command", "checkbutton", "cascade"):
            out.append((menu.entrycget(i, "label"), menu.entrycget(i, "accelerator")
                        if kind == "command" else ""))
    return out


@pytest.mark.parametrize("mac", [True, False])
def test_file_menu_entries(monkeypatch, mac):
    _mac(monkeypatch, mac)
    root = _bare_app()
    try:
        root._build_menu()
        entries = _file_menu_entries(root)
        labels = [lbl for lbl, _ in entries]
        if mac:
            assert ("Browse...", "Command-O") in entries
            assert not any(l in ("Exit", "Quit") for l in labels)
            assert not any("Ctrl+" in l for l in labels)
        else:
            assert ("Browse...                          Ctrl+O", "") in entries
            assert "Exit                                  Ctrl+Q" in labels
    finally:
        root.destroy()


@pytest.mark.parametrize("mac", [True, False])
def test_main_window_bindings_and_clipboard_hook(monkeypatch, mac):
    root = _bare_app()
    try:
        _mac(monkeypatch, mac)
        root._install_clipboard_keys()
        assert bool(root.bind_all("<Control-KeyPress>")) is (not mac)
    finally:
        root.destroy()


@pytest.mark.parametrize("mac,word", [(True, "Quit"), (False, "Exit")])
def test_queued_tasks_prompt_wording(monkeypatch, mac, word):
    import types

    from app.app import App

    seen: list[tuple] = []
    monkeypatch.setattr(
        "app.app.messagebox",
        types.SimpleNamespace(askyesno=lambda *a, **k: seen.append(a) or False),
    )
    _mac(monkeypatch, mac)
    app = types.SimpleNamespace(
        _exit_from_tray=True, app_config={}, tray=None,
        queue=[types.SimpleNamespace(status="running")], download_queue=[],
    )
    App.on_exit(app)  # type: ignore[arg-type]
    title, text = seen[0]
    assert title == f"{word} with queued tasks"
    assert text.endswith(f"{word} anyway?")
