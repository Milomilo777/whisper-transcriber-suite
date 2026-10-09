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
        assert labels[-1] == "Send usage statistics"
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
        ["/music/a b.mp3", "/music/c.mp4", "/music/d.wav"])
    assert host._mac_pending_opens == []  # type: ignore[attr-defined]


def test_files_wait_while_the_quick_start_window_is_open(aqua: None, host: _Host) -> None:
    host._quick_start_open = True
    mac_native.install(host)
    host.tk.call("::tk::mac::OpenDocument", "/music/a.mp3")
    assert not _pump(host, lambda: host.open_paths.called, seconds=0.3)  # type: ignore[attr-defined]
    host._quick_start_open = False
    assert _pump(host, lambda: host.open_paths.called)  # type: ignore[attr-defined]
    host.open_paths.assert_called_once_with(["/music/a.mp3"])  # type: ignore[attr-defined]


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
    assert platform_mod.reveal_label("Open folder") == "Reveal in Finder"
    assert platform_mod.reveal_label("Open log folder", "Log Folder") == "Reveal Log Folder in Finder"
    for other in ("win32", "linux"):
        platform_name(other)
        assert platform_mod.reveal_label("Open folder") == "Open folder"
        assert platform_mod.reveal_label("Open log folder", "Log Folder") == "Open log folder"


def test_macos_reveals_the_file_inside_its_folder(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch, tmp_path: Any,
) -> None:
    platform_name("darwin")
    out = tmp_path / "talk.srt"
    out.write_text("1\n", encoding="utf-8")
    calls: list[list[str]] = []
    monkeypatch.setattr(platform_mod.subprocess, "run", lambda cmd, **k: calls.append(cmd))
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


def test_queue_context_menu_wording(platform_name: Callable[[str], None]) -> None:
    platform_name("darwin")
    assert app_mod.reveal_label("Open output folder") == "Reveal in Finder"
    assert app_mod.reveal_label("Open download folder") == "Reveal in Finder"
    platform_name("win32")
    assert app_mod.reveal_label("Open output folder") == "Open output folder"


def test_help_menu_log_folder_item_is_worded_for_the_platform(
    platform_name: Callable[[str], None], monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)
    platform_name("darwin")
    root = _menu_host()
    try:
        root._build_menu()
        assert "Reveal Log Folder in Finder" in _labels(root._help_menu)
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
