"""macOS native integration (``app/mac_native.py`` and its call sites in the app).

The Tk windowing system here is win32 or x11, so the tests pretend to be Aqua by
patching ``mac_native.is_aqua`` (the one switch every call site asks) and, where
a label or accelerator depends on it, ``sys.platform`` of the module that reads
it. Every Aqua test has a twin showing Windows and Linux (``win32``, ``x11``)
come out exactly as before.

What Tk really does with these hooks on a Mac (menus filled by macOS, Apple
events reaching ``::tk::mac::OpenDocument``) is proved by
``tools/mac_native_probe.py`` in the macOS VM, not here.
"""
from __future__ import annotations

import time
import tkinter as tk
import types
from typing import Any, Callable
from unittest.mock import MagicMock

import pytest

import app.app as app_mod
from app import mac_native, shortcuts
from app.app import App
from app.widgets import platform as platform_mod
from tests.app.test_menu_and_empty_state import _labels, _menu_host


@pytest.fixture
def aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pretend Tk runs on macOS: the windowing system and the platform label."""
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: True)
    monkeypatch.setattr(shortcuts, "is_mac", lambda: True)


@pytest.fixture(params=["win32", "x11"])
def not_aqua(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)
    monkeypatch.setattr(shortcuts, "is_mac", lambda: False)
    return str(request.param)


def _pump(root: tk.Misc, done: Callable[[], bool], seconds: float = 3.0) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        root.update()
        if done():
            return True
        time.sleep(0.01)
    return False


class _Host(tk.Tk):
    """A Tk root with the attributes ``mac_native`` reads and the actions it calls."""


def _host(**overrides: Any) -> _Host:
    root = _Host()
    root.withdraw()
    root._show_about = MagicMock(name="_show_about")  # type: ignore[attr-defined]
    root.open_advanced_dialog = MagicMock(name="open_advanced_dialog")  # type: ignore[attr-defined]
    root.open_paths = MagicMock(name="open_paths")  # type: ignore[attr-defined]
    root._start_ran = True  # type: ignore[attr-defined]
    root._quick_start_open = False  # type: ignore[attr-defined]
    root._closing = False  # type: ignore[attr-defined]
    for name, value in overrides.items():
        setattr(root, name, value)
    return root


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mac_native, "DRAIN_POLL_MS", 10)
    root = _host()
    try:
        yield root
    finally:
        root.destroy()


def _tcl_commands(root: tk.Misc, pattern: str) -> tuple[str, ...]:
    return tuple(root.tk.splitlist(root.tk.call("info", "commands", pattern)))


# ------------------------------------------------------------ is_aqua, helpers

def test_is_aqua_reads_the_tk_windowing_system() -> None:
    def fake(system: str) -> types.SimpleNamespace:
        return types.SimpleNamespace(tk=types.SimpleNamespace(call=lambda *a: system))

    assert mac_native.is_aqua(fake("aqua")) is True
    assert mac_native.is_aqua(fake("win32")) is False
    assert mac_native.is_aqua(fake("x11")) is False


def test_is_aqua_is_false_when_the_query_fails_or_there_is_no_tk() -> None:
    def boom(*_a: Any) -> str:
        raise tk.TclError("no display")

    assert mac_native.is_aqua(types.SimpleNamespace(tk=types.SimpleNamespace(call=boom))) is False
    assert mac_native.is_aqua(types.SimpleNamespace()) is False  # a half-built widget


def test_clean_paths_keeps_order_and_drops_blanks() -> None:
    assert mac_native.clean_paths(["/a b/c.mp4", "", "  ", "/d.wav"]) == ["/a b/c.mp4", "/d.wav"]


# ---------------------------------------------------------------- menu bar

def _cascade(bar: tk.Menu, label: str) -> tk.Menu:
    for i in range(bar.index("end") + 1):
        if bar.type(i) == "cascade" and bar.entrycget(i, "label") == label:
            return bar.nametowidget(bar.entrycget(i, "menu"))
    raise AssertionError(f"no {label} menu")


def _built(aqua_on: bool, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: aqua_on)
    monkeypatch.setattr(shortcuts, "is_mac", lambda: aqua_on)
    root = _menu_host()
    root._build_menu()
    return root


def test_aqua_menu_bar_has_the_window_menu_between_view_and_help(
    aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(True, monkeypatch)
    try:
        assert _labels(root._menubar) == ["File", "View", "Window", "Help"]
    finally:
        root.destroy()


def test_aqua_window_and_help_menus_carry_the_special_names_tk_looks_for(
    aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(True, monkeypatch)
    try:
        assert str(_cascade(root._menubar, "Window")).rsplit(".", 1)[-1] == "window"
        assert str(_cascade(root._menubar, "Help")).rsplit(".", 1)[-1] == "help"
        assert root._help_menu is _cascade(root._menubar, "Help")
    finally:
        root.destroy()


def test_aqua_help_menu_drops_the_about_item_the_app_menu_now_carries(
    aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(True, monkeypatch)
    try:
        labels = _labels(root._help_menu)
        assert "About" not in labels
        assert labels[-1] != "-"  # no dangling separator where About was
        assert labels[-1] == "Usage statistics"
    finally:
        root.destroy()


def test_aqua_update_sign_indexes_still_point_at_their_items(
    aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(True, monkeypatch)
    try:
        help_menu = root._help_menu
        assert help_menu.entrycget(root._check_updates_index, "label") == app_mod._CHECK_FOR_UPDATES_LABEL
        assert root._menubar.entrycget(root._help_cascade_index, "label") == "Help"
    finally:
        root.destroy()


def test_aqua_file_menu_has_close_window_with_the_command_w_accelerator(
    aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(True, monkeypatch)
    try:
        file_menu = _cascade(root._menubar, "File")
        entry = next(i for i in range(file_menu.index("end") + 1)
                     if file_menu.type(i) == "command" and file_menu.entrycget(i, "label") == "Close Window")
        assert file_menu.entrycget(entry, "accelerator") == "Command-W"
        closed: list[Any] = []
        monkeypatch.setattr(mac_native, "close_front_window", lambda a: closed.append(a) or True)
        file_menu.invoke(entry)
        assert closed == [root]
        # macOS has no Exit item here: the app menu carries Quit.
        assert not any(label.startswith("Exit") for label in _labels(file_menu))
    finally:
        root.destroy()


def test_other_windowing_systems_build_the_menu_bar_exactly_as_before(
    not_aqua: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(False, monkeypatch)
    try:
        assert _labels(root._menubar) == ["File", "View", "Help"]
        assert str(_cascade(root._menubar, "Help")).rsplit(".", 1)[-1] != "help"
        help_labels = _labels(root._help_menu)
        assert help_labels[-1] == "About" and help_labels[-2] == "-"
        assert "Close Window" not in _labels(_cascade(root._menubar, "File"))
        assert root._menubar.entrycget(root._help_cascade_index, "label") == "Help"
    finally:
        root.destroy()


def test_aqua_help_title_never_gets_the_update_dot_but_the_item_does(
    aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """macOS adds its search field to a menu titled exactly Help (probe, 2026-10-09)."""
    root = _built(True, monkeypatch)
    try:
        root.app_config = {}
        monkeypatch.setattr("core.updates.passive_sign_version", lambda *_a: "9.9.9")
        App._refresh_update_signs(root)  # type: ignore[arg-type]
        assert root._menubar.entrycget(root._help_cascade_index, "label") == "Help"
        assert "9.9.9" in root._help_menu.entrycget(root._check_updates_index, "label")
    finally:
        root.destroy()


def test_other_systems_still_put_the_update_dot_on_the_help_title(
    not_aqua: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _built(False, monkeypatch)
    try:
        root.app_config = {}
        monkeypatch.setattr("core.updates.passive_sign_version", lambda *_a: "9.9.9")
        App._refresh_update_signs(root)  # type: ignore[arg-type]
        assert str(root._menubar.entrycget(root._help_cascade_index, "label")).startswith("Help")
        assert root._menubar.entrycget(root._help_cascade_index, "label") != "Help"
    finally:
        root.destroy()


# ------------------------------------------------------- app menu commands

def test_install_registers_the_native_commands_on_aqua(aqua: None, host: _Host) -> None:
    assert mac_native.install(host) is True
    for name in ("tkAboutDialog", "::tk::mac::ShowPreferences", "::tk::mac::ShowHelp",
                 "::tk::mac::ReopenApplication", "::tk::mac::OpenDocument"):
        assert _tcl_commands(host, name), name


def test_install_registers_nothing_elsewhere(not_aqua: str, host: _Host) -> None:
    assert mac_native.install(host) is False
    for name in ("tkAboutDialog", "::tk::mac::ShowPreferences", "::tk::mac::ShowHelp",
                 "::tk::mac::ReopenApplication", "::tk::mac::OpenDocument"):
        assert _tcl_commands(host, name) == (), name
    assert not hasattr(host, "_mac_pending_opens")


def test_about_item_opens_the_apps_own_about_dialog(aqua: None, host: _Host) -> None:
    mac_native.install(host)
    host.tk.call("tkAboutDialog")  # what Tk runs for the app menu's About item
    host._show_about.assert_called_once_with()  # type: ignore[attr-defined]


def test_settings_item_opens_the_advanced_settings_dialog(aqua: None, host: _Host) -> None:
    mac_native.install(host)
    host.tk.call("::tk::mac::ShowPreferences")  # Settings... / Command-comma
    host.open_advanced_dialog.assert_called_once_with()  # type: ignore[attr-defined]


def test_about_and_settings_wait_for_a_modal_window_and_for_startup(aqua: None, host: _Host) -> None:
    mac_native.install(host)
    host.grab_current = lambda: object()  # type: ignore[method-assign]
    host.tk.call("tkAboutDialog")
    host.tk.call("::tk::mac::ShowPreferences")
    host.grab_current = lambda: None  # type: ignore[method-assign]
    host._start_ran = False
    host.tk.call("tkAboutDialog")
    host.tk.call("::tk::mac::ShowPreferences")
    host._show_about.assert_not_called()  # type: ignore[attr-defined]
    host.open_advanced_dialog.assert_not_called()  # type: ignore[attr-defined]


def test_help_item_opens_the_user_documentation_page(
    aqua: None, host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import webbrowser

    from core import star_invite

    opened: list[str] = []
    monkeypatch.setattr(webbrowser, "open", lambda url, *a, **k: opened.append(url) or True)
    mac_native.install(host)
    host.tk.call("::tk::mac::ShowHelp")
    assert opened == [f"{star_invite.REPO_URL}/blob/master/docs/README.md"]


def test_a_failing_handler_is_logged_not_raised_into_tk(
    aqua: None, host: _Host, caplog: pytest.LogCaptureFixture,
) -> None:
    host._show_about.side_effect = RuntimeError("boom")  # type: ignore[attr-defined]
    mac_native.install(host)
    host.tk.call("tkAboutDialog")  # must not raise
    assert "About handler failed" in caplog.text


# --------------------------------------------------------- Finder: open files

def test_files_opened_from_finder_wait_for_startup_then_go_through_open_paths(
    aqua: None, host: _Host,
) -> None:
    host._start_ran = False
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a b.mp3", "/music/c.mp4")
    host.tk.call("::tk::mac::OpenDocument", "/music/d.wav")
    host.update()
    host.open_paths.assert_not_called()  # type: ignore[attr-defined]
    host._start_ran = True
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]
    # One hand-over, in the order macOS sent them: the same path as a drop.
    host.open_paths.assert_called_once_with(  # type: ignore[attr-defined]
        ["/music/a b.mp3", "/music/c.mp4", "/music/d.wav"], require_media=True)
    assert host._mac_pending_opens == []  # type: ignore[attr-defined]


def test_files_wait_while_the_quick_start_window_is_open(aqua: None, host: _Host) -> None:
    host._quick_start_open = True
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.3)  # type: ignore[attr-defined]
    host._quick_start_open = False
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]
    host.open_paths.assert_called_once_with(  # type: ignore[attr-defined]
        ["/music/a.mp3"], require_media=True)


def test_files_wait_while_a_modal_window_holds_the_grab(aqua: None, host: _Host) -> None:
    """The first-run model folder dialog and the model gate are modal."""
    host.grab_current = lambda: object()  # type: ignore[method-assign]
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.3)  # type: ignore[attr-defined]
    host.grab_current = lambda: None  # type: ignore[method-assign]
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]


def test_only_one_poll_timer_runs_however_many_events_arrive(aqua: None, host: _Host) -> None:
    host._quick_start_open = True
    mac_native.install(host)
    for i in range(5):
        host.tk.call("::tk::mac::OpenDocument", f"/music/{i}.mp3")
    assert len(host.tk.splitlist(host.tk.call("after", "info"))) == 1


def test_files_arriving_while_the_app_exits_are_dropped(aqua: None, host: _Host) -> None:
    host._closing = True
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.2)  # type: ignore[attr-defined]


def test_blank_open_events_queue_nothing(aqua: None, host: _Host) -> None:
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "")
    host.update()
    assert host._mac_pending_opens == []  # type: ignore[attr-defined]
    host.open_paths.assert_not_called()  # type: ignore[attr-defined]


def test_the_open_handler_survives_a_failing_open_paths(
    aqua: None, host: _Host, caplog: pytest.LogCaptureFixture,
) -> None:
    mac_native.install(host)
    host.after = MagicMock(side_effect=RuntimeError("boom"))  # type: ignore[method-assign]
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")  # must not raise
    assert "OpenDocument handler failed" in caplog.text


# ---------------------------------------------------------------- Dock click

@pytest.mark.parametrize("state", ["withdrawn", "iconic"])
def test_clicking_the_dock_icon_shows_a_hidden_or_minimised_window(
    aqua: None, host: _Host, state: str,
) -> None:
    mac_native.install(host)
    if state == "withdrawn":
        host.withdraw()
    else:
        host.deiconify()
        host.update()
        host.iconify()
    host.update()
    if str(host.state()) not in ("withdrawn", "iconic"):
        pytest.skip("this display has no window manager to minimise a window")
    host.tk.call("::tk::mac::ReopenApplication")
    assert str(host.state()) == "normal"


def test_reopen_while_exiting_does_nothing(aqua: None, host: _Host) -> None:
    mac_native.install(host)
    host._closing = True
    host.tk.call("::tk::mac::ReopenApplication")
    assert str(host.state()) == "withdrawn"


# ------------------------------------------------------------ Command-W

def _window_with_focus(root: _Host, monkeypatch: pytest.MonkeyPatch) -> tuple[tk.Toplevel, tk.Entry]:
    win = tk.Toplevel(root)
    entry = tk.Entry(win)
    entry.pack()
    monkeypatch.setattr(root, "focus_get", lambda: entry)
    return win, entry


def test_command_w_runs_the_secondary_windows_own_close_handler(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    win, _entry = _window_with_focus(host, monkeypatch)
    asked: list[str] = []
    win.protocol("WM_DELETE_WINDOW", lambda: asked.append("close"))  # e.g. the unsaved-edits prompt
    assert mac_native.close_front_window(host) is True
    assert asked == ["close"]
    assert win.winfo_exists()  # the handler decides (the user may have kept the window)


def test_command_w_runs_a_close_handler_that_is_a_tcl_script(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Tk's own dialogs register a multi-word script, not one command name.
    win, _entry = _window_with_focus(host, monkeypatch)
    host.tk.call("wm", "protocol", win, "WM_DELETE_WINDOW", "set ::wts_cmd_w_script_ran yes")
    try:
        assert mac_native.close_front_window(host) is True
        assert host.tk.globalgetvar("wts_cmd_w_script_ran") == "yes"
    finally:
        host.tk.call("unset", "-nocomplain", "::wts_cmd_w_script_ran")


def test_command_w_destroys_a_window_that_has_no_close_handler(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    win, _entry = _window_with_focus(host, monkeypatch)
    assert mac_native.close_front_window(host) is True
    assert not win.winfo_exists()


def test_command_w_never_closes_the_main_window(host: _Host, monkeypatch: pytest.MonkeyPatch) -> None:
    entry = tk.Entry(host)
    monkeypatch.setattr(host, "focus_get", lambda: entry)
    host.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("the main window must not close"))
    assert mac_native.close_front_window(host) is False


@pytest.mark.parametrize("focus", ["none", "key_error"])
def test_command_w_without_a_focused_widget_does_nothing(
    host: _Host, monkeypatch: pytest.MonkeyPatch, focus: str,
) -> None:
    def key_error() -> None:
        raise KeyError("popdown")  # what tkinter raises for a combobox popup

    monkeypatch.setattr(host, "focus_get", (lambda: None) if focus == "none" else key_error)
    assert mac_native.close_front_window(host) is False


def test_the_unsaved_edits_prompt_stays_in_charge_of_command_w(
    host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    """A real viewer with unsaved edits asks first; Cancel keeps it, Yes closes it."""
    from app.dialogs import transcript_viewer as tv
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    monkeypatch.setattr(host, "focus_get", lambda: viewer)
    viewer._dirty = True
    asked: list[str] = []
    answers = iter([False, True])
    monkeypatch.setattr(
        tv.messagebox, "askyesno", lambda title, *a, **k: asked.append(title) or next(answers))
    assert mac_native.close_front_window(host) is True
    assert viewer.winfo_exists()  # answered no: the edits are kept
    assert mac_native.close_front_window(host) is True
    assert not viewer.winfo_exists()
    assert asked == ["Discard changes?", "Discard changes?"]


# ---------------------------------------- Command-W follows the key window, not Tk's focus
#
# Found in the macOS VM: after the Find dialog and an alert of the viewer were closed, File >
# Close Window did nothing (three tries) because Tk reported no focus while the viewer was still
# the front window. macOS decides Command-W by the key window, so AppKit is asked first.

def _front(monkeypatch: pytest.MonkeyPatch, root: _Host, key: str | None,
           stack: list[tk.Misc], focus: tk.Misc | None = None) -> None:
    """Fake what AppKit and Tk report: the key window's title, the stacking order (front first)
    and Tk's focus widget."""
    monkeypatch.setattr(mac_native, "key_window_title", lambda: key)
    monkeypatch.setattr(mac_native, "_stack_front_first", lambda _app: [str(w) for w in stack])
    monkeypatch.setattr(root, "focus_get", lambda: focus)


def _two_windows(root: _Host) -> tuple[tk.Toplevel, tk.Toplevel]:
    viewer = tk.Toplevel(root)
    viewer.title("Transcript - talk.json")
    find = tk.Toplevel(viewer)
    find.title("Find and replace")
    root.title("Whisper Transcriber Suite")
    return viewer, find


def test_command_w_closes_the_key_window_when_tk_has_lost_its_focus(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, _find = _two_windows(host)
    asked: list[str] = []
    viewer.protocol("WM_DELETE_WINDOW", lambda: asked.append("viewer"))
    _front(monkeypatch, host, "Transcript - talk.json", [viewer, host], focus=None)
    assert mac_native.close_front_window(host) is True
    assert asked == ["viewer"]


def test_command_w_closes_the_key_window_when_tk_still_names_the_main_window(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, _find = _two_windows(host)
    asked: list[str] = []
    viewer.protocol("WM_DELETE_WINDOW", lambda: asked.append("viewer"))
    stale = tk.Entry(host)
    _front(monkeypatch, host, "Transcript - talk.json", [viewer, host], focus=stale)
    assert mac_native.close_front_window(host) is True
    assert asked == ["viewer"]


def test_command_w_never_closes_a_window_behind_the_key_main_window(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tk's focus can be stale in the viewer while the person works in the main window."""
    viewer, _find = _two_windows(host)
    viewer.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("the viewer is not the front window"))
    stale = tk.Entry(viewer)
    _front(monkeypatch, host, "Whisper Transcriber Suite", [viewer, host], focus=stale)
    assert mac_native.close_front_window(host) is False


def test_command_w_closes_the_find_dialog_in_front_of_its_viewer(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, find = _two_windows(host)
    viewer.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("only the dialog is in front"))
    _front(monkeypatch, host, "Find and replace", [find, viewer, host])
    assert mac_native.close_front_window(host) is True
    assert not find.winfo_exists() and viewer.winfo_exists()


def test_command_w_with_two_windows_of_one_title_takes_the_front_one(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = tk.Toplevel(host), tk.Toplevel(host)
    first.title("Transcript - a.json")
    second.title("Transcript - a.json")
    _front(monkeypatch, host, "Transcript - a.json", [second, first, host])
    assert mac_native.close_front_window(host) is True
    assert not second.winfo_exists() and first.winfo_exists()


def test_command_w_does_nothing_when_the_key_window_is_not_one_of_ours(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A native panel is key (no title matches) and Tk has no focus in a secondary window."""
    viewer, _find = _two_windows(host)
    viewer.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("a native panel is the key window"))
    _front(monkeypatch, host, "Open", [viewer, host], focus=None)
    assert mac_native.close_front_window(host) is False
    _front(monkeypatch, host, "Open", [viewer, host], focus=tk.Entry(host))   # focus in the main window
    assert mac_native.close_front_window(host) is False


def test_an_unmatched_key_title_falls_back_to_the_secondary_window_tk_has_focus_in(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The title can differ in a way no normalisation fixes (changed after open): the original
    "Close Window does nothing" must not come back while Tk still knows the focused window."""
    viewer, _find = _two_windows(host)
    asked: list[str] = []
    viewer.protocol("WM_DELETE_WINDOW", lambda: asked.append("viewer"))
    _front(monkeypatch, host, "A title no window has", [viewer, host], focus=tk.Entry(viewer))
    assert mac_native.close_front_window(host) is True
    assert asked == ["viewer"]


def _nfd(text: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFD", text)
    assert decomposed != text      # the sample really differs between the two forms
    return decomposed


@pytest.mark.parametrize("tk_form, key_form", [("nfc", "nfd"), ("nfd", "nfc")])
def test_command_w_matches_a_title_in_another_unicode_form(
    host: _Host, monkeypatch: pytest.MonkeyPatch, tk_form: str, key_form: str,
) -> None:
    """AppKit and Tk may hand back the same Persian title composed differently (alef-madda is
    one code point or alef + madda)."""
    composed = "آزمون — نمونه صدا.json"
    forms = {"nfc": composed, "nfd": _nfd(composed)}
    viewer = tk.Toplevel(host)
    viewer.title(forms[tk_form])
    asked: list[str] = []
    viewer.protocol("WM_DELETE_WINDOW", lambda: asked.append("viewer"))
    _front(monkeypatch, host, forms[key_form], [viewer, host], focus=None)
    assert mac_native.close_front_window(host) is True
    assert asked == ["viewer"]


def test_command_w_ignores_blank_edges_of_a_title(host: _Host, monkeypatch: pytest.MonkeyPatch) -> None:
    viewer = tk.Toplevel(host)
    viewer.title("Transcript - talk.json")
    _front(monkeypatch, host, "  Transcript - talk.json \n", [viewer, host], focus=None)
    assert mac_native.close_front_window(host) is True
    assert not viewer.winfo_exists()


def test_command_w_matches_a_title_with_a_non_bmp_character(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer = tk.Toplevel(host)
    viewer.title("Talk \U0001F3A4 notes.json")
    _front(monkeypatch, host, "Talk \U0001F3A4 notes.json", [viewer, host], focus=None)
    assert mac_native.close_front_window(host) is True
    assert not viewer.winfo_exists()


# --- a modal dialog's grab: only that dialog (or a window of its own) may be closed

def _grab(monkeypatch: pytest.MonkeyPatch, root: _Host, holder: tk.Misc | None) -> list[int]:
    monkeypatch.setattr(root, "grab_current", lambda: holder)
    bells: list[int] = []
    monkeypatch.setattr(root, "bell", lambda *a, **k: bells.append(1))
    return bells


def test_command_w_leaves_other_windows_alone_while_a_dialog_holds_the_grab(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, find = _two_windows(host)
    dialog = tk.Toplevel(host)
    viewer.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("a modal dialog holds the grab"))
    bells = _grab(monkeypatch, host, tk.Entry(dialog))   # the grab holder is a widget in the dialog
    _front(monkeypatch, host, "Transcript - talk.json", [viewer, dialog, host])
    assert mac_native.close_front_window(host) is False
    assert bells == [1] and viewer.winfo_exists() and find.winfo_exists()


def test_command_w_closes_the_dialog_that_holds_the_grab(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = tk.Toplevel(host)
    dialog.title("Modal question")
    bells = _grab(monkeypatch, host, dialog)
    _front(monkeypatch, host, "Modal question", [dialog, host])
    assert mac_native.close_front_window(host) is True
    assert not dialog.winfo_exists() and bells == []


def test_command_w_closes_a_window_opened_by_the_dialog_that_holds_the_grab(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dialog = tk.Toplevel(host)
    child = tk.Toplevel(dialog)
    child.title("Opened from the dialog")
    _grab(monkeypatch, host, dialog)
    _front(monkeypatch, host, "Opened from the dialog", [child, dialog, host])
    assert mac_native.close_front_window(host) is True
    assert not child.winfo_exists() and dialog.winfo_exists()


def test_a_sibling_whose_name_starts_like_the_grab_window_is_not_part_of_it(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``.!toplevel1`` and ``.!toplevel10`` are different windows (prefix tests need a dot)."""
    wins = [tk.Toplevel(host) for _ in range(10)]
    first, tenth = wins[0], wins[9]
    assert str(tenth).startswith(str(first))
    tenth.title("Tenth")
    tenth.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("not a descendant of the grab window"))
    bells = _grab(monkeypatch, host, first)
    _front(monkeypatch, host, "Tenth", [tenth, first, host])
    assert mac_native.close_front_window(host) is False
    assert bells == [1]


def test_a_grab_that_cannot_be_read_does_not_stop_command_w(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, _find = _two_windows(host)

    def broken() -> None:
        raise tk.TclError("no grab")

    monkeypatch.setattr(host, "grab_current", broken)
    _front(monkeypatch, host, "Transcript - talk.json", [viewer, host])
    assert mac_native.close_front_window(host) is True


def test_command_w_matches_a_persian_title(host: _Host, monkeypatch: pytest.MonkeyPatch) -> None:
    viewer = tk.Toplevel(host)
    viewer.title("متن — نمونه صدا.json")
    _front(monkeypatch, host, "متن — نمونه صدا.json", [viewer, host])
    assert mac_native.close_front_window(host) is True
    assert not viewer.winfo_exists()


def test_without_appkit_command_w_uses_the_front_window_when_tk_has_no_focus(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer, _find = _two_windows(host)
    asked: list[str] = []
    viewer.protocol("WM_DELETE_WINDOW", lambda: asked.append("viewer"))
    _front(monkeypatch, host, None, [viewer, host], focus=None)
    assert mac_native.close_front_window(host) is True
    assert asked == ["viewer"]


def test_without_appkit_and_with_only_the_main_window_nothing_closes(
    host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    host.protocol("WM_DELETE_WINDOW", lambda: pytest.fail("the main window must not close"))
    _front(monkeypatch, host, None, [host], focus=None)
    assert mac_native.close_front_window(host) is False
    _front(monkeypatch, host, None, [], focus=None)
    assert mac_native.close_front_window(host) is False


def test_the_unsaved_edits_prompt_stays_in_charge_of_the_key_window(
    host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    from app.dialogs import transcript_viewer as tv
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    title = str(viewer.title())
    _front(monkeypatch, host, title, [viewer, host], focus=None)
    viewer._dirty = True
    answers = iter([False, True])
    asked: list[str] = []
    monkeypatch.setattr(
        tv.messagebox, "askyesno", lambda t, *a, **k: asked.append(t) or next(answers))
    assert mac_native.close_front_window(host) is True
    assert viewer.winfo_exists()
    assert mac_native.close_front_window(host) is True
    assert not viewer.winfo_exists()
    assert asked == ["Discard changes?", "Discard changes?"]


def test_the_real_stacking_order_lists_the_front_window_first() -> None:
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    try:
        if str(root.tk.call("tk", "windowingsystem")) == "aqua":
            pytest.skip("Aqua orders windows only for an active app; proved in the macOS VM")
        root.title("main")
        back, front = tk.Toplevel(root), tk.Toplevel(root)
        back.title("back")
        front.title("front")
        root.update()
        front.lift()
        root.update()
        order = mac_native._stack_front_first(root)
        assert order.index(str(front)) < order.index(str(back))
        back.lift()
        root.update()
        assert mac_native._stack_front_first(root)[0] == str(back)
    finally:
        root.destroy()


def test_the_key_window_is_unknown_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mac_native.sys, "platform", "win32")
    assert mac_native.key_window_title() is None


def test_the_key_window_is_unknown_when_the_objc_runtime_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_native.sys, "platform", "darwin")
    monkeypatch.setattr(mac_native.ctypes.util, "find_library", lambda _name: None)
    assert mac_native.key_window_title() is None
    monkeypatch.setattr(mac_native.ctypes.util, "find_library", lambda _name: "libobjc.fake")

    def refuse(*_a: Any, **_k: Any) -> Any:
        raise OSError("no such library")

    monkeypatch.setattr(mac_native.ctypes, "PyDLL", refuse)
    assert mac_native.key_window_title() is None


# ---------------------------------------------------------------- About dialog placement

class _Shown:
    """A main window (or screen) with a position and a size, recording ``geometry`` calls."""

    def __init__(self, x: int, y: int, w: int, h: int, *, viewable: bool = True,
                 screen: tuple[int, int] = (1440, 900), system: str = "aqua") -> None:
        self.tk = types.SimpleNamespace(call=lambda *a: system)
        self._box, self._viewable, self._screen = (x, y, w, h), viewable, screen
        self.geometries: list[str] = []

    def winfo_toplevel(self) -> "_Shown":
        return self

    def winfo_viewable(self) -> bool:
        return self._viewable

    def winfo_rootx(self) -> int:
        return self._box[0]

    def winfo_rooty(self) -> int:
        return self._box[1]

    def winfo_width(self) -> int:
        return self._box[2]

    def winfo_height(self) -> int:
        return self._box[3]

    def winfo_screenwidth(self) -> int:
        return self._screen[0]

    def winfo_screenheight(self) -> int:
        return self._screen[1]

    def geometry(self, value: str) -> None:
        self.geometries.append(value)


def test_the_about_dialog_is_centred_over_the_main_window_on_aqua() -> None:
    main, dialog = _Shown(100, 60, 1000, 800), _Shown(0, 0, 0, 0)
    mac_native.centre_over(dialog, main, 680, 620)
    assert dialog.geometries == ["+260+150"]


def test_a_centred_window_on_the_main_screen_stays_on_it_below_the_menu_bar() -> None:
    dialog = _Shown(0, 0, 0, 0)
    mac_native.centre_over(dialog, _Shown(1100, 600, 300, 250), 680, 620)
    assert dialog.geometries == ["+760+280"]          # right/bottom edge clamped to the screen
    dialog = _Shown(0, 0, 0, 0)
    mac_native.centre_over(dialog, _Shown(0, 0, 200, 100), 680, 620)
    assert dialog.geometries == ["+0+28"]             # never left of the screen or under the menu bar


@pytest.mark.parametrize("box, expected", [
    ((-1500, 100, 1000, 800), "+-1340+190"),      # a monitor left of the main one
    ((1600, 50, 1000, 800), "+1760+140"),         # right of it, beyond its width
    ((100, -1000, 1000, 800), "+260+-910"),       # above it
])
def test_a_window_is_centred_on_a_main_window_that_lies_off_the_main_screen(
    box: tuple[int, int, int, int], expected: str,
) -> None:
    """Tk accepts negative coordinates (a monitor left of or above the main one): no clamp."""
    dialog = _Shown(0, 0, 0, 0)
    mac_native.centre_over(dialog, _Shown(*box), 680, 620)
    assert dialog.geometries == [expected]


def test_a_main_window_half_off_the_main_screen_keeps_the_dialog_on_it() -> None:
    """Its middle is on the main screen: the dialog is clamped onto that screen, not off the edge."""
    dialog = _Shown(0, 0, 0, 0)
    mac_native.centre_over(dialog, _Shown(-300, 200, 1000, 800), 680, 620)
    assert dialog.geometries == ["+0+280"]            # x clamped to the left edge; bottom held at 900


@pytest.mark.parametrize("system", ["win32", "x11"])
def test_a_window_is_left_where_the_system_puts_it_elsewhere(system: str) -> None:
    dialog = _Shown(0, 0, 0, 0, system=system)
    mac_native.centre_over(dialog, _Shown(100, 60, 1000, 800), 680, 620)
    assert dialog.geometries == []


def test_a_window_is_not_centred_over_a_hidden_main_window() -> None:
    dialog = _Shown(0, 0, 0, 0)
    mac_native.centre_over(dialog, _Shown(100, 60, 1000, 800, viewable=False), 680, 620)
    assert dialog.geometries == []


def _open_about(host: _Host, monkeypatch: pytest.MonkeyPatch, screen_h: int = 900) -> tk.Toplevel:
    # The dialog size and the screen are the display's (DPI scale, work area); fix both so the
    # expected position does not depend on the machine or on what an earlier test left behind.
    monkeypatch.setattr(app_mod, "scaled_size", lambda _w, width, height: (width, height))
    monkeypatch.setattr(host, "winfo_screenwidth", lambda: 1440)
    monkeypatch.setattr(host, "winfo_screenheight", lambda: screen_h)
    host.app_config = {}  # type: ignore[attr-defined]
    host._star_open_page = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(host, "winfo_viewable", lambda: True)
    monkeypatch.setattr(host, "winfo_rootx", lambda: 100)
    monkeypatch.setattr(host, "winfo_rooty", lambda: 60)
    monkeypatch.setattr(host, "winfo_width", lambda: 1000)
    monkeypatch.setattr(host, "winfo_height", lambda: 800)
    before = set(host.winfo_children())
    App._show_about(host)  # type: ignore[arg-type]  # duck-typed host
    (dlg,) = set(host.winfo_children()) - before
    host.update_idletasks()
    return dlg  # type: ignore[return-value]


def _geometry(dlg: tk.Toplevel) -> tuple[int, int, int, int]:
    import re

    m = re.fullmatch(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)", dlg.wm_geometry())
    assert m, dlg.wm_geometry()
    return tuple(int(g) for g in m.groups())  # type: ignore[return-value]


def test_the_apps_about_dialog_opens_centred_on_aqua(
    host: _Host, aqua: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dlg = _open_about(host, monkeypatch)
    _w, _h, x, y = _geometry(dlg)   # not on screen yet: its size still reads 1x1
    assert (x, y) == (100 + (1000 - 680) // 2, 60 + (800 - 620) // 2) == (260, 150)


@pytest.mark.parametrize("screen_h, y", [(700, 80), (500, 28)])
def test_the_apps_about_dialog_stays_on_a_screen_shorter_than_the_main_window(
    host: _Host, aqua: None, monkeypatch: pytest.MonkeyPatch, screen_h: int, y: int,
) -> None:
    """Main window at y=60, 800 high; the screen is shorter than it (700) or than the dialog (500)."""
    dlg = _open_about(host, monkeypatch, screen_h)
    _w, _h, x, got_y = _geometry(dlg)
    assert (x, got_y) == (260, y)


def test_the_apps_about_dialog_is_not_placed_by_the_app_elsewhere(
    host: _Host, not_aqua: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    dlg = _open_about(host, monkeypatch)
    _w, _h, x, y = _geometry(dlg)
    assert (x, y) != (260, 150)


# ------------------------------------------------------- window marks, viewer

class _Win:
    """A window that records ``wm attributes`` calls and reports a windowing system."""

    def __init__(self, system: str) -> None:
        self.tk = types.SimpleNamespace(call=lambda *a: system)
        self.attrs: list[tuple[str, Any]] = []

    def wm_attributes(self, name: str, value: Any) -> None:
        self.attrs.append((name, value))


def test_title_path_and_modified_marks_are_set_on_aqua() -> None:
    win = _Win("aqua")
    mac_native.set_title_path(win, "/t/talk.json")
    mac_native.set_modified(win, True)
    mac_native.set_modified(win, False)
    assert win.attrs == [("-titlepath", "/t/talk.json"), ("-modified", True), ("-modified", False)]


@pytest.mark.parametrize("system", ["win32", "x11"])
def test_window_marks_are_not_touched_elsewhere(system: str) -> None:
    win = _Win(system)
    mac_native.set_title_path(win, "/t/talk.json")
    mac_native.set_modified(win, True)
    assert win.attrs == []


def test_a_window_that_rejects_the_marks_is_not_fatal() -> None:
    win = _Win("aqua")

    def reject(*_a: Any) -> None:
        raise tk.TclError("bad attribute")

    win.wm_attributes = reject  # type: ignore[method-assign]
    mac_native.set_title_path(win, "/t/talk.json")
    mac_native.set_modified(win, True)


def test_the_viewers_dirty_flag_drives_the_close_button_dot(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.dialogs.transcript_viewer import TranscriptViewer

    marks: list[bool] = []
    monkeypatch.setattr(mac_native, "set_modified", lambda _w, flag: marks.append(flag))
    viewer = TranscriptViewer.__new__(TranscriptViewer)
    assert viewer._dirty is False  # a partly built viewer reads as clean
    viewer._dirty = True
    viewer._dirty = False
    assert marks == [True, False]
    assert viewer._dirty is False


def test_a_half_built_viewer_can_still_be_marked_dirty() -> None:
    from app.dialogs.transcript_viewer import TranscriptViewer

    viewer = TranscriptViewer.__new__(TranscriptViewer)  # no Tk behind it
    viewer._dirty = True
    assert viewer._dirty is True


# ------------------------------------------------------------ Finder wording

@pytest.fixture
def platform_name(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Make ``app.widgets.platform`` believe it runs on the named platform."""
    import os

    def set_platform(name: str) -> None:
        monkeypatch.setattr(platform_mod, "sys", types.SimpleNamespace(platform=name))
        monkeypatch.setattr(platform_mod, "os", types.SimpleNamespace(
            name="nt" if name == "win32" else "posix", path=os.path,
            startfile=lambda p: platform_mod.started.append(p)))
    return set_platform


def test_reveal_label_says_reveal_in_finder_on_macos_only(platform_name: Callable[[str], None]) -> None:
    platform_name("darwin")
    assert platform_mod.reveal_label("Open JSON folder") == "Reveal in Finder"
    for other in ("win32", "linux"):
        platform_name(other)
        assert platform_mod.reveal_label("Open JSON folder") == "Open JSON folder"


def test_folder_label_keeps_a_folder_wording_on_macos(platform_name: Callable[[str], None]) -> None:
    platform_name("darwin")
    assert platform_mod.folder_label("Open log folder", "Log Folder") == "Open Log Folder in Finder"
    for other in ("win32", "linux"):
        platform_name(other)
        assert platform_mod.folder_label("Open log folder", "Log Folder") == "Open log folder"


def test_folder_action_label_reveals_only_when_there_is_a_file_to_select(
    platform_name: Callable[[str], None],
) -> None:
    platform_name("darwin")
    assert platform_mod.folder_action_label("Open folder", "Output Folder", "/x/a.srt") == "Reveal in Finder"
    assert platform_mod.folder_action_label("Open folder", "Output Folder", None) == "Open Output Folder in Finder"
    platform_name("win32")
    assert platform_mod.folder_action_label("Open folder", "Output Folder", "/x/a.srt") == "Open folder"
    assert platform_mod.folder_action_label("Open folder", "Output Folder", None) == "Open folder"


def test_open_r_failing_falls_back_to_opening_the_folder(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    platform_name("darwin")
    out = tmp_path / "talk.srt"
    out.write_text("1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def run(cmd: list[str], **_k: Any) -> Any:
        calls.append(cmd)
        return types.SimpleNamespace(returncode=1 if cmd[1] == "-R" else 0)

    monkeypatch.setattr(platform_mod.subprocess, "run", run)
    platform_mod.open_folder(str(tmp_path), select=str(out))
    assert calls == [["open", "-R", str(out)], ["open", str(tmp_path)]]


def test_open_r_raising_falls_back_to_opening_the_folder(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    platform_name("darwin")
    out = tmp_path / "talk.srt"
    out.write_text("1\n", encoding="utf-8")
    calls: list[list[str]] = []

    def run(cmd: list[str], **_k: Any) -> Any:
        calls.append(cmd)
        if cmd[1] == "-R":
            raise OSError("no open")
        return types.SimpleNamespace(returncode=0)

    monkeypatch.setattr(platform_mod.subprocess, "run", run)
    platform_mod.open_folder(str(tmp_path), select=str(out))
    assert calls[-1] == ["open", str(tmp_path)]


def test_macos_reveals_the_file_inside_its_folder(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    platform_name("darwin")
    out = tmp_path / "talk.srt"
    out.write_text("1\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(
        platform_mod.subprocess, "run",
        lambda cmd, **k: calls.append(cmd) or types.SimpleNamespace(returncode=0))
    platform_mod.open_folder(str(tmp_path), select=str(out))
    assert calls == [["open", "-R", str(out)]]


def test_macos_opens_the_folder_when_the_file_to_select_is_gone(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    platform_name("darwin")
    calls: list[list[str]] = []
    monkeypatch.setattr(platform_mod.subprocess, "run", lambda cmd, **k: calls.append(cmd))
    platform_mod.open_folder(str(tmp_path), select=str(tmp_path / "gone.srt"))
    platform_mod.open_folder(str(tmp_path))
    assert calls == [["open", str(tmp_path)], ["open", str(tmp_path)]]


def test_windows_and_linux_ignore_the_file_to_select(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    out = tmp_path / "talk.srt"
    out.write_text("1\n", encoding="utf-8")
    started: list[str] = []
    monkeypatch.setattr(platform_mod, "started", started, raising=False)
    ran: list[list[str]] = []
    monkeypatch.setattr(platform_mod.subprocess, "run", lambda cmd, **k: ran.append(cmd))
    platform_name("win32")
    platform_mod.open_folder(str(tmp_path), select=str(out))
    assert started == [str(tmp_path)] and ran == []
    platform_name("linux")
    platform_mod.open_folder(str(tmp_path), select=str(out))
    assert ran == [["xdg-open", str(tmp_path)]]


def _result_card(root: tk.Tk, tmp_path: Any):
    from tests.app.test_transcript_json_pick import _buttons, _srt_plus_chapters
    from tests.app.test_transcript_json_pick import _result_card as card

    fake = card(root, _srt_plus_chapters(tmp_path))
    return fake, _buttons(fake.last_result_body)


@pytest.fixture
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


def test_result_card_button_says_reveal_in_finder_and_selects_the_output(
    platform_name: Callable[[str], None], tk_root: tk.Tk, tmp_path: Any,
) -> None:
    platform_name("darwin")
    fake, buttons = _result_card(tk_root, tmp_path)
    assert "Open folder" not in buttons
    buttons["Reveal in Finder"].invoke()
    fake._open_folder.assert_called_once_with(str(tmp_path), select=str(tmp_path / "talk.srt"))


def test_result_card_button_keeps_its_wording_on_windows_and_linux(
    platform_name: Callable[[str], None], tk_root: tk.Tk, tmp_path: Any,
) -> None:
    platform_name("win32")
    _fake, buttons = _result_card(tk_root, tmp_path)
    assert "Open folder" in buttons and "Reveal in Finder" not in buttons


def test_result_card_with_nothing_to_select_says_open_folder_in_finder(
    platform_name: Callable[[str], None], tk_root: tk.Tk, tmp_path: Any,
) -> None:
    from tests.app.test_transcript_json_pick import _buttons, _srt_plus_chapters
    from tests.app.test_transcript_json_pick import _result_card as card

    platform_name("darwin")
    task = _srt_plus_chapters(tmp_path)
    task.output_paths = []  # nothing was written that the card could select
    (tmp_path / "talk.srt").unlink()
    (tmp_path / "talk.chapters.json").unlink()
    fake = card(tk_root, task)
    buttons = _buttons(fake.last_result_body)
    assert "Open Folder in Finder" in buttons and "Reveal in Finder" not in buttons
    buttons["Open Folder in Finder"].invoke()
    fake._open_folder.assert_called_once_with(str(tmp_path), select=None)


def test_queue_and_download_menus_pick_their_wording_from_the_helper() -> None:
    import inspect

    queue_src = inspect.getsource(App.menu_row)
    download_src = inspect.getsource(App.download_menu_row)
    assert 'folder_action_label("Open output folder"' in queue_src
    assert 'folder_action_label("Open download folder"' in download_src
    assert "reveal_label(" not in queue_src + download_src


def test_task_output_file_is_the_first_output_that_exists(tmp_path: Any) -> None:
    from app.domain.task_outputs import task_output_file

    real = tmp_path / "talk.srt"
    real.write_text("1\n", encoding="utf-8")
    task = types.SimpleNamespace(
        file_path=str(tmp_path / "talk.mp4"), output_paths=[str(tmp_path / "gone.json"), str(real)])
    assert task_output_file(task) == str(real)
    task.output_paths = [str(tmp_path / "gone.json")]
    assert task_output_file(task) is None
    assert task_output_file(types.SimpleNamespace(file_path="x")) is None


def test_help_menu_log_folder_item_is_worded_for_the_platform(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)
    platform_name("darwin")
    root = _menu_host()
    try:
        root._build_menu()
        assert "Open Log Folder in Finder" in _labels(root._help_menu)
        assert "Open log folder" not in _labels(root._help_menu)
    finally:
        root.destroy()
    platform_name("linux")
    root = _menu_host()
    try:
        root._build_menu()
        assert "Open log folder" in _labels(root._help_menu)
    finally:
        root.destroy()


# ------------------------------------------------------------ init order

def test_the_native_handlers_exist_before_the_first_event_loop_turn() -> None:
    import inspect

    src = inspect.getsource(App.__init__)
    menu_at = src.find("self._build_menu()")
    flag_at = src.find("self._start_ran = False")
    install_at = src.find("mac_native.install(self)")
    mainloop_at = src.find("self.after(100, self._on_start)")
    assert -1 not in (menu_at, flag_at, install_at, mainloop_at)
    assert menu_at < flag_at < install_at < mainloop_at


def test_start_ran_is_set_before_the_first_run_windows_open() -> None:
    import inspect

    src = inspect.getsource(App._on_start)
    assert src.find("self._start_ran = True") != -1
    assert src.find("self._start_ran = True") < src.find("should_show(self.app_config)")


def test_the_quick_start_flag_the_queue_reads_is_still_set_by_the_app() -> None:
    import inspect

    src = inspect.getsource(App)
    assert "self._quick_start_open = True" in src and "self._quick_start_open = False" in src


def test_a_viewer_shows_its_transcript_as_the_title_proxy_icon(
    host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    seen: list[tuple[Any, str]] = []
    monkeypatch.setattr(mac_native, "set_title_path", lambda w, p: seen.append((w, p)))
    json_path = _write_outputs(tmp_path, ["json"])
    viewer = _open(host, json_path)
    try:
        assert seen == [(viewer, json_path)]
    finally:
        viewer._dirty = False
        viewer._on_close()


def test_a_real_viewer_marks_unsaved_edits_and_clears_the_mark(
    host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    marks: list[bool] = []
    monkeypatch.setattr(mac_native, "set_modified", lambda _w, flag: marks.append(flag))
    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    try:
        assert marks == [False]  # opened clean
        viewer._dirty = True
        assert marks == [False, True]
    finally:
        viewer._dirty = False
        viewer._on_close()


def test_a_viewer_still_opens_when_the_window_rejects_the_marks(
    aqua: None, host: _Host, tmp_path: Any,
) -> None:
    """Here (not a Mac) wm attributes has no -titlepath/-modified: the viewer must not care."""
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    try:
        viewer._dirty = True
        assert viewer._dirty is True
    finally:
        viewer._dirty = False
        viewer._on_close()


# --------------------------------------- readiness: native alerts and flags

def test_files_wait_while_an_exit_question_is_open(aqua: None, host: _Host) -> None:
    """The quit question is a native alert: it holds no Tk grab."""
    host._exit_prompt_open = True
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.3)  # type: ignore[attr-defined]
    host._exit_prompt_open = False
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]


def test_files_wait_while_the_model_folder_dialog_is_open(aqua: None, host: _Host) -> None:
    host._hub_setup_open = True
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.3)  # type: ignore[attr-defined]
    host._hub_setup_open = False
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]


def test_about_and_settings_beep_during_an_exit_question_or_the_model_folder_dialog(
    aqua: None, host: _Host,
) -> None:
    mac_native.install(host)
    for flag in ("_exit_prompt_open", "_hub_setup_open"):
        setattr(host, flag, True)
        host.tk.call("tkAboutDialog")
        host.tk.call("::tk::mac::ShowPreferences")
        setattr(host, flag, False)
    host._show_about.assert_not_called()  # type: ignore[attr-defined]
    host.open_advanced_dialog.assert_not_called()  # type: ignore[attr-defined]


def _mapped(window: tk.Toplevel, monkeypatch: pytest.MonkeyPatch) -> tk.Toplevel:
    """Pretend the window is on screen (the test root itself stays withdrawn)."""
    monkeypatch.setattr(window, "winfo_viewable", lambda: 1)
    return window


def test_a_mapped_transient_window_counts_as_modal_even_without_a_grab(
    aqua: None, host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three dialogs swallow a failed grab_set; the window itself still blocks."""
    dialog = tk.Toplevel(host)
    dialog.transient(host)
    _mapped(dialog, monkeypatch)
    mac_native.install(host)
    host.tk.call("tkAboutDialog")
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.3)  # type: ignore[attr-defined]
    host._show_about.assert_not_called()  # type: ignore[attr-defined]
    dialog.destroy()
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]


def test_windows_that_are_not_modal_do_not_block(
    aqua: None, host: _Host, monkeypatch: pytest.MonkeyPatch,
) -> None:
    hidden = tk.Toplevel(host)  # transient but not on screen
    hidden.transient(host)
    free = _mapped(tk.Toplevel(host), monkeypatch)  # on screen but not transient
    flagged = tk.Toplevel(host)
    flagged.transient(host)
    flagged._non_modal = True  # type: ignore[attr-defined]
    _mapped(flagged, monkeypatch)
    assert mac_native._modal_open(host) is False
    free.destroy()


def test_transcript_viewers_are_not_modal(
    host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    from app.dialogs.transcript_viewer import TranscriptViewer
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    assert TranscriptViewer._non_modal is True
    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    _mapped(viewer, monkeypatch)
    try:
        assert str(viewer.wm_transient())  # transient, like a modal dialog
        assert mac_native._modal_open(host) is False
    finally:
        viewer._dirty = False
        viewer._on_close()


def test_the_search_window_is_not_modal() -> None:
    from app.dialogs.search_dialog import SearchDialog

    assert SearchDialog._non_modal is True


def test_hub_setup_flag_is_set_while_the_dialog_is_open_and_cleared_on_done(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.dialogs import hub_setup
    from core import hub

    captured: dict[str, Any] = {}
    monkeypatch.setattr(hub, "is_hub_configured", lambda _c: False)
    monkeypatch.setattr(
        hub_setup, "ensure_hub_configured",
        lambda _m, _c, on_done=None, **_k: captured.setdefault("on_done", on_done))
    fake = types.SimpleNamespace(
        app_config={}, log=MagicMock(), _hub_setup_open=False,
        _refresh_model_selector=MagicMock(), _refresh_engine_selector=MagicMock(),
    )
    App._ensure_hub_folder(fake)  # type: ignore[arg-type]
    assert fake._hub_setup_open is True
    monkeypatch.setattr(app_mod, "load_config", lambda: {})
    captured["on_done"]("/models")
    assert fake._hub_setup_open is False


def test_hub_setup_flag_is_cleared_when_the_dialog_cannot_open(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.dialogs import hub_setup
    from core import hub

    def boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("no dialog")

    monkeypatch.setattr(hub, "is_hub_configured", lambda _c: False)
    monkeypatch.setattr(hub_setup, "ensure_hub_configured", boom)
    fake = types.SimpleNamespace(app_config={}, log=MagicMock(), _hub_setup_open=False)
    App._ensure_hub_folder(fake)  # type: ignore[arg-type]
    assert fake._hub_setup_open is False


def test_hub_flag_exists_before_the_first_event_loop_turn() -> None:
    import inspect

    src = inspect.getsource(App.__init__)
    assert src.find("self._hub_setup_open = False") != -1
    assert src.find("self._hub_setup_open = False") < src.find("mac_native.install(self)")


# --------------------------------------- Finder files: the media check

def _open_paths_host(tmp_path: Any) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        fv=types.SimpleNamespace(set=MagicMock()), nb=MagicMock(), t1=object(),
        log=MagicMock(), _bulk_enqueue=MagicMock(return_value=0))


def test_a_non_media_file_from_finder_is_refused_with_the_drop_message(tmp_path: Any) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("x", encoding="utf-8")
    fake = _open_paths_host(tmp_path)
    App.open_paths(fake, [str(note)], require_media=True)  # type: ignore[arg-type]
    fake.fv.set.assert_not_called()
    assert "Ignored 1 dropped item(s)" in fake.log.call_args[0][0]


def test_a_media_file_from_finder_is_picked_like_a_drop(tmp_path: Any) -> None:
    song = tmp_path / "song.mp3"
    song.write_bytes(b"x")
    fake = _open_paths_host(tmp_path)
    App.open_paths(fake, [str(song)], require_media=True)  # type: ignore[arg-type]
    fake.fv.set.assert_called_once_with(str(song))


def test_only_the_media_files_of_a_mixed_finder_open_are_queued(tmp_path: Any) -> None:
    a, b, note = tmp_path / "a.mp3", tmp_path / "b.mkv", tmp_path / "n.txt"
    for f in (a, b, note):
        f.write_bytes(b"x")
    fake = _open_paths_host(tmp_path)
    App.open_paths(fake, [str(a), str(note), str(b)], require_media=True)  # type: ignore[arg-type]
    fake._bulk_enqueue.assert_called_once_with([str(a), str(b)])


def test_a_dropped_file_on_windows_keeps_its_behaviour_without_the_media_check(tmp_path: Any) -> None:
    """A drop (require_media off) still picks any existing file, as before."""
    note = tmp_path / "notes.txt"
    note.write_text("x", encoding="utf-8")
    fake = _open_paths_host(tmp_path)
    App.open_paths(fake, [str(note)])  # type: ignore[arg-type]
    fake.fv.set.assert_called_once_with(str(note))


# --------------------------------------- viewer: Open JSON folder

def test_viewer_json_folder_button_says_reveal_in_finder_and_selects_the_json(
    platform_name: Callable[[str], None], host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    from app.dialogs import transcript_viewer as tv
    from tests.app.test_transcript_json_pick import _buttons
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    platform_name("darwin")
    json_path = _write_outputs(tmp_path, ["json"])
    viewer = _open(host, json_path)
    try:
        buttons = _buttons(viewer)
        assert "Reveal in Finder" in buttons and "Open JSON folder" not in buttons
        seen: list[Any] = []
        monkeypatch.setattr(tv, "open_folder", lambda *a, **k: seen.append((a, k)))
        buttons["Reveal in Finder"].invoke()
        assert seen == [((str(tmp_path),), {"parent": viewer, "select": json_path})]
    finally:
        viewer._dirty = False
        viewer._on_close()


def test_a_big_window_can_keep_the_bottom_of_the_screen_free_for_the_dock() -> None:
    dialog = _Shown(0, 0, 0, 0)
    mac_native.centre_over(
        dialog, _Shown(1100, 600, 300, 250), 680, 620, reserve_bottom=mac_native.DOCK_ROOM_PX,
    )
    assert dialog.geometries == ["+760+140"]          # 900 - 620 - 140, not the 280 of the default


@pytest.mark.parametrize("screen_h, asked, expected", [
    (800, 720, 632),      # the Dock room comes off a small screen
    (1080, 720, 720),     # a big screen keeps the size asked for
    (500, 720, 520),      # never below the fitted minimum
    (500, 400, 400),      # nor above what was asked
])
def test_a_big_window_is_fitted_above_the_dock(
    aqua: None, screen_h: int, asked: int, expected: int,
) -> None:
    screen = types.SimpleNamespace(
        tk=types.SimpleNamespace(call=lambda *a: "aqua"), winfo_screenheight=lambda: screen_h)
    assert mac_native.fit_height(screen, asked) == expected


def test_a_window_height_is_left_alone_off_aqua(not_aqua: str) -> None:
    screen = types.SimpleNamespace(
        tk=types.SimpleNamespace(call=lambda *a: "x11"), winfo_screenheight=lambda: 500)
    assert mac_native.fit_height(screen, 720) == 720


def _viewer_over_a_1280x800_mac(host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any):
    """Open the transcript viewer over a shown main window on a faked 1280x800 Mac screen."""
    from app import dpi
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    monkeypatch.setattr(dpi, "_is_mac", lambda: True)
    monkeypatch.setattr(dpi, "scale_factor", lambda _w: 1.0)
    monkeypatch.setattr(dpi, "work_area", lambda _w: (0, 0, 1280, 800, False))
    for name, value in (("winfo_viewable", True), ("winfo_rootx", 20), ("winfo_rooty", 22),
                        ("winfo_width", 1240), ("winfo_height", 716),
                        ("winfo_screenwidth", 1280), ("winfo_screenheight", 800)):
        monkeypatch.setattr(host, name, lambda v=value: v)
    monkeypatch.setattr(tk.Misc, "winfo_screenheight", lambda self: 800)  # the viewer's own screen
    seen: list[str] = []
    real = tk.Toplevel.geometry

    def geometry(self: tk.Toplevel, value: Any = None) -> Any:
        if value is not None:
            seen.append(str(value))
        return real(self, value)

    monkeypatch.setattr(tk.Toplevel, "geometry", geometry)
    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    return viewer, seen


def test_the_viewer_opens_inside_a_1280x800_mac_screen(
    aqua: None, host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    viewer, seen = _viewer_over_a_1280x800_mac(host, monkeypatch, tmp_path)
    try:
        assert seen == ["1180x632", "+50+28"]        # 800 - menu bar 28 - Dock room 140
        width, height, x, y = 1180, 632, 50, 28
        assert x + width <= 1280                       # right edge on screen
        assert y + 28 + height <= 800 - 100            # title bar and window end above a 100 px Dock
        assert viewer.minsize() == (1180, 520)         # it may be dragged shorter, not wider
    finally:
        viewer._dirty = False
        viewer._on_close()


def test_the_viewer_is_left_to_the_system_off_macos(
    not_aqua: str, host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    viewer, seen = _viewer_over_a_1280x800_mac(host, monkeypatch, tmp_path)
    try:
        assert len(seen) == 1 and seen[0].count("+") == 0   # a size only, no position
        assert viewer.minsize() == (1180, 660)              # the old floor: the launch size
    finally:
        viewer._dirty = False
        viewer._on_close()


def test_viewer_json_folder_button_is_unchanged_on_windows_and_linux(
    platform_name: Callable[[str], None], host: _Host, monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    from app.dialogs import transcript_viewer as tv
    from tests.app.test_transcript_json_pick import _buttons
    from tests.app.test_viewer_edit_safety import _open, _write_outputs

    platform_name("linux")
    viewer = _open(host, _write_outputs(tmp_path, ["json"]))
    try:
        buttons = _buttons(viewer)
        assert "Open JSON folder" in buttons
        opened: list[str] = []
        monkeypatch.setattr(tv, "_os_open", lambda path, parent=None: opened.append(path))
        monkeypatch.setattr(tv, "open_folder", lambda *a, **k: pytest.fail("not on this platform"))
        buttons["Open JSON folder"].invoke()
        assert opened == [str(tmp_path)]
    finally:
        viewer._dirty = False
        viewer._on_close()

def test_open_document_calls_a_moment_apart_arrive_as_one_batch(aqua: None, host: _Host) -> None:
    """Finder sends a three-file Open With as two calls about 0.2 s apart (macOS 13)."""
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3", "/music/b.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.2)  # type: ignore[attr-defined]
    host.tk.call("::tk::mac::OpenDocument", "/music/c.mp3")
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]
    host.open_paths.assert_called_once_with(  # type: ignore[attr-defined]
        ["/music/a.mp3", "/music/b.mp3", "/music/c.mp3"], require_media=True)
    assert len(host.tk.splitlist(host.tk.call("after", "info"))) == 0
