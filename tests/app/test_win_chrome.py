"""Windows title bar / border that follow the app theme (card C2.75).

ctypes is faked at the ``_Native`` boundary, so the calls and their order are pinned on every OS.
One test at the end talks to the real DWM on a Windows PC (a withdrawn Tk window only).
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
from typing import Any

import pytest

from app.theme import win_chrome as wc
from core import config as cfg

WIN10 = 19045
WIN10_OLD = 17763
WIN11 = 22631


class FakeNative:
    """Records DWM calls. ``refuse`` maps attribute -> HRESULT to return; ``boom`` raises."""

    def __init__(self, refuse: dict[int, int] | None = None, boom: set[int] | None = None,
                 parent_of: dict[int, int] | None = None) -> None:
        self.refuse = refuse or {}
        self.boom = boom or set()
        self.parent_of = parent_of
        self.calls: list[tuple[int, int, int]] = []
        self.redraws: list[int] = []

    def parent(self, hwnd: int) -> int:
        if self.parent_of is not None:
            return self.parent_of.get(hwnd, 0)
        return hwnd + 1000

    def set_attribute(self, hwnd: int, attribute: int, value: int) -> int:
        if attribute in self.boom:
            raise OSError("dwmapi missing")
        self.calls.append((hwnd, attribute, value))
        return self.refuse.get(attribute, 0)

    def redraw_frame(self, hwnd: int) -> bool:
        self.redraws.append(hwnd)
        return True

    def attrs(self) -> list[int]:
        return [a for _h, a, _v in self.calls]


class FakeWidget:
    def __init__(self, inner: int = 7) -> None:
        self.inner = inner

    def update_idletasks(self) -> None:
        return None

    def winfo_id(self) -> int:
        return self.inner


def _apply(theme: str, native: FakeNative, build: int, widget: Any = None) -> dict[int, int]:
    return wc.apply(widget or FakeWidget(), theme, native=native, build=build, platform="win32")


@pytest.fixture
def windows(monkeypatch: pytest.MonkeyPatch):
    """This process behaves as Windows 10 with a fake native layer; returns the fake."""
    native = FakeNative()
    monkeypatch.setattr(wc, "_platform", lambda: "win32")
    monkeypatch.setattr(wc, "_native_cache", native)
    monkeypatch.setattr(wc, "windows_build", lambda: WIN10)
    monkeypatch.delenv(wc.ENV_KILL_SWITCH, raising=False)
    return native


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    r.withdraw()
    yield r
    r.destroy()


# ----------------------------------------------------------------- colours and handle

def test_colorref_is_blue_green_red() -> None:
    assert wc.colorref("#102030") == 0x302010
    assert wc.colorref("#1c1c1c") == 0x1C1C1C
    assert wc.colorref("#ff0000") == 0x0000FF


def test_the_handle_is_the_parent_frame_of_tks_inner_window() -> None:
    assert wc.window_handle(FakeWidget(7), FakeNative()) == 1007


def test_a_window_without_a_frame_yet_has_no_handle_not_the_inner_window() -> None:
    assert wc.window_handle(FakeWidget(7), FakeNative(parent_of={})) == 0


# ------------------------------------------------------------------------ Windows 10

def test_windows_10_dark_sets_the_flag_and_redraws() -> None:
    native = FakeNative()
    results = _apply("dark", native, WIN10)
    assert native.calls == [(1007, 20, 1)]
    assert native.redraws == [1007]
    assert results == {20: 0}


def test_windows_10_light_clears_the_flag() -> None:
    native = FakeNative()
    _apply("light", native, WIN10)
    assert native.calls == [(1007, 20, 0)]


def test_windows_10_never_makes_the_windows_11_colour_calls() -> None:
    native = FakeNative()
    _apply("dark", native, WIN10)
    assert not {34, 35, 36} & set(native.attrs())


def test_an_older_windows_10_gets_the_old_attribute_number() -> None:
    native = FakeNative(refuse={20: 0x80070057})   # E_INVALIDARG
    results = _apply("dark", native, WIN10_OLD)
    assert native.attrs() == [20, 19]
    assert results == {20: 0x80070057, 19: 0}
    assert native.redraws == [1007]


def test_both_numbers_refused_is_harmless_and_does_not_redraw() -> None:
    native = FakeNative(refuse={20: 1, 19: 1})
    results = _apply("dark", native, WIN10_OLD)
    assert results == {20: 1, 19: 1}
    assert native.redraws == []


def test_a_failing_native_call_is_ignored_and_logged_once(caplog) -> None:
    native = FakeNative(boom={20, 19})
    with caplog.at_level(logging.INFO, logger=wc.logger.name):
        assert _apply("dark", native, WIN10) == {20: -1, 19: -1}
        _apply("dark", native, WIN10)
    assert len([r for r in caplog.records if "attribute 20 call failed" in r.getMessage()]) == 1


def test_no_window_handle_means_no_calls() -> None:
    native = FakeNative(parent_of={})
    assert wc.apply(FakeWidget(0), "dark", native=native, build=WIN10, platform="win32") == {}
    assert native.calls == []


# ------------------------------------------------------------------------ Windows 11

def test_windows_11_dark_colours_match_the_dark_panel() -> None:
    native = FakeNative()
    _apply("dark", native, WIN11)
    assert native.calls == [
        (1007, 20, 1),
        (1007, 35, 0x1C1C1C),    # caption = dark panel
        (1007, 34, 0x1C1C1C),    # border
        (1007, 36, 0xFAFAFA),    # text
    ]
    assert native.redraws == []   # only Windows 10 needs the frame redraw


def test_windows_11_light_colours_match_the_light_panel() -> None:
    native = FakeNative()
    _apply("light", native, WIN11)
    assert native.calls == [
        (1007, 20, 0), (1007, 35, 0xFAFAFA), (1007, 34, 0xFAFAFA), (1007, 36, 0x1C1C1C),
    ]


def test_windows_11_starts_at_build_22000() -> None:
    low, high = FakeNative(), FakeNative()
    _apply("dark", low, 21999)
    _apply("dark", high, 22000)
    assert 35 not in low.attrs() and 35 in high.attrs()


def test_a_refused_colour_does_not_stop_the_others() -> None:
    native = FakeNative(refuse={35: 0x80070057})
    results = _apply("dark", native, WIN11)
    assert native.attrs() == [20, 35, 34, 36]
    assert results[35] == 0x80070057 and results[34] == 0 and results[36] == 0


def test_an_unknown_theme_name_is_dark() -> None:
    native = FakeNative()
    _apply("anything", native, WIN10)
    assert native.calls == [(1007, 20, 1)]


# ------------------------------------------------- macOS / Linux: nothing is touched (pinned)

@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_systems_make_no_native_call(platform) -> None:
    native = FakeNative()
    assert wc.apply(FakeWidget(), "dark", native=native, build=WIN11, platform=platform) == {}
    assert native.calls == [] and native.redraws == []


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_systems_install_and_apply_all_do_nothing(monkeypatch, root, platform) -> None:
    monkeypatch.setattr(wc, "_platform", lambda: platform)
    monkeypatch.setattr(wc, "_native", lambda: pytest.fail("native layer loaded off Windows"))
    wc.install(root, "dark")
    assert wc.apply_all(root, "light") == 0
    assert not getattr(root, "_wts_chrome_bound", False)


# ---------------------------------------------------------------------- kill switch

def test_config_switch_stops_every_call(windows, root) -> None:
    wc.set_enabled(False)
    assert wc.enabled() is False
    assert _apply("dark", windows, WIN11) == {}
    wc.install(root, "dark")
    assert wc.apply_all(root, "dark") == 0
    assert windows.calls == []


@pytest.mark.parametrize("value", ["1", "true", "yes", "anything"])
def test_env_switch_stops_every_call(windows, root, monkeypatch, value) -> None:
    monkeypatch.setenv(wc.ENV_KILL_SWITCH, value)
    assert wc.enabled() is False
    wc.install(root, "dark")
    assert windows.calls == []


@pytest.mark.parametrize("value", ["", "0", "false", "off"])
def test_env_switch_off_values_leave_it_on(windows, monkeypatch, value) -> None:
    monkeypatch.setenv(wc.ENV_KILL_SWITCH, value)
    assert wc.enabled() is True


def test_the_env_switch_is_read_live(windows, monkeypatch) -> None:
    assert wc.enabled() is True
    monkeypatch.setenv(wc.ENV_KILL_SWITCH, "1")
    assert wc.enabled() is False


def test_the_config_default_is_on_and_a_bool() -> None:
    assert cfg.DEFAULT_CONFIG["native_window_theme"] is True


def test_the_app_reads_the_config_key() -> None:
    from pathlib import Path
    text = (Path(__file__).resolve().parents[2] / "app" / "app.py").read_text(encoding="utf-8")
    assert 'win_chrome.set_enabled(bool(self.app_config.get("native_window_theme", True)))' in text


# ------------------------------------------- real Tk windows with the native layer faked

def _dialog(root: tk.Tk, *, override: bool = False) -> tk.Toplevel:
    top = tk.Toplevel(root)
    top.withdraw()
    if override:
        top.overrideredirect(True)
    return top


def _show(top: tk.Toplevel) -> None:
    """Fire the <Map> a real show would (without putting a window on the desktop)."""
    top.update_idletasks()
    top.event_generate("<Map>")
    top.update_idletasks()


def _handles(native: FakeNative) -> set[int]:
    return {h for h, a, _v in native.calls if a == 20}


def test_install_themes_the_root_and_a_dialog_made_later(windows, root) -> None:
    wc.install(root, "dark")
    assert windows.calls == [(root.winfo_id() + 1000, 20, 1)]
    dlg = _dialog(root)
    _show(dlg)
    assert (dlg.winfo_id() + 1000, 20, 1) in windows.calls


def test_a_second_show_does_not_redraw_the_frame(windows, root) -> None:
    wc.install(root, "dark")
    dlg = _dialog(root)
    _show(dlg)
    before = len(windows.calls)
    _show(dlg)   # minimise / restore
    assert len(windows.calls) == before


def test_a_theme_switch_reaches_every_open_dialog(windows, root) -> None:
    wc.install(root, "dark")
    first, second = _dialog(root), _dialog(root)
    _show(first)
    _show(second)
    windows.calls.clear()
    assert wc.apply_all(root, "light") == 3   # root + two dialogs, shown or not
    assert _handles(windows) == {w.winfo_id() + 1000 for w in (root, first, second)}
    assert {v for _h, a, v in windows.calls if a == 20} == {0}


def test_a_dialog_opened_after_a_switch_gets_the_new_theme(windows, root) -> None:
    wc.install(root, "dark")
    wc.apply_all(root, "light")
    windows.calls.clear()
    late = _dialog(root)
    _show(late)
    assert windows.calls == [(late.winfo_id() + 1000, 20, 0)]


def test_a_dialog_nested_in_a_dialog_is_reached(windows, root) -> None:
    wc.install(root, "dark")
    outer = _dialog(root)
    inner = tk.Toplevel(outer)
    inner.withdraw()
    windows.calls.clear()
    assert wc.apply_all(root, "light") == 3
    assert (inner.winfo_id() + 1000) in _handles(windows)


def test_a_tooltip_style_window_has_no_frame_and_is_skipped(windows, root) -> None:
    wc.install(root, "dark")
    tip = _dialog(root, override=True)
    windows.calls.clear()
    _show(tip)
    assert wc.apply_all(root, "light") == 1   # the root only
    assert (tip.winfo_id() + 1000) not in _handles(windows)


def test_menus_are_not_windows_with_a_frame(windows, root) -> None:
    menubar = tk.Menu(root)
    menubar.add_cascade(label="File", menu=tk.Menu(menubar, tearoff=False))
    root.configure(menu=menubar)
    popup = tk.Menu(root, tearoff=False)
    popup.add_command(label="x")
    wc.install(root, "dark")
    windows.calls.clear()
    assert wc.apply_all(root, "light") == 1
    assert _handles(windows) == {root.winfo_id() + 1000}


def test_a_destroyed_dialog_leaves_nothing_behind(windows, root) -> None:
    wc.install(root, "dark")
    dlg = _dialog(root)
    _show(dlg)
    dlg.destroy()
    windows.calls.clear()
    assert wc.apply_all(root, "light") == 1


def test_a_refusing_native_layer_never_breaks_window_creation(root, monkeypatch) -> None:
    refusing = FakeNative(refuse={20: 5, 19: 5, 35: 5, 34: 5, 36: 5}, boom=set())
    monkeypatch.setattr(wc, "_platform", lambda: "win32")
    monkeypatch.setattr(wc, "_native_cache", refusing)
    monkeypatch.setattr(wc, "windows_build", lambda: WIN11)
    wc.install(root, "dark")
    dlg = _dialog(root)
    _show(dlg)
    assert dlg.winfo_exists()


def test_a_native_layer_that_cannot_load_never_breaks_the_app(root, monkeypatch) -> None:
    def cannot_load() -> Any:
        raise OSError("dwmapi.dll not found")

    monkeypatch.setattr(wc, "_platform", lambda: "win32")
    monkeypatch.setattr(wc, "_native_cache", None)
    monkeypatch.setattr(wc, "_native", cannot_load)
    wc.install(root, "dark")
    assert wc.apply_all(root, "light") == 0
    dlg = _dialog(root)
    _show(dlg)


def test_the_apps_restyle_themes_the_frames_of_a_window_with_menus(windows, root) -> None:
    """App._restyle on a real root that has a menu bar and an open dialog (what a switch does)."""
    pytest.importorskip("sv_ttk")
    from app import app as app_module
    from app.theme import tokens

    menubar = tk.Menu(root)
    menubar.add_cascade(label="View", menu=tk.Menu(menubar, tearoff=False))
    root.configure(menu=menubar)
    wc.install(root, "light")
    dlg = _dialog(root)
    windows.calls.clear()
    app_module.App._restyle(root, "dark")   # type: ignore[arg-type]  # duck-typed host
    assert tokens.current_theme() == "dark"
    assert _handles(windows) == {root.winfo_id() + 1000, dlg.winfo_id() + 1000}
    assert {v for _h, a, v in windows.calls if a == 20} == {1}
    windows.calls.clear()
    app_module.App._restyle(root, "light")   # type: ignore[arg-type]
    assert tokens.current_theme() == "light"
    assert {v for _h, a, v in windows.calls if a == 20} == {0}


def test_app_wiring_order() -> None:
    import inspect
    from app.app import App

    src = inspect.getsource(App.__init__)
    colours = src.find("theme_colours.apply(self, start_theme)")
    install = src.find("win_chrome.install(self, start_theme)")
    watcher = src.find("SystemThemeWatcher(")
    sync = src.find("self._sync_system_theme_watch(self.theme_var.get())")
    assert 0 < colours < install and watcher < sync and install < sync
    assert "self._restyle(name)" in inspect.getsource(App.apply_theme)
    assert "self._sync_system_theme_watch(name)" in inspect.getsource(App.apply_theme)


def test_reset_for_tests_restores_the_defaults(windows) -> None:
    wc.set_enabled(False)
    wc._failed.add("x")
    wc.reset_for_tests()
    assert wc._config_enabled is True and wc._failed == set() and wc._theme == "light"


# ------------------------------------------------------- the real DWM (Windows 10 1903+ only)

@pytest.mark.skipif(sys.platform != "win32" or sys.getwindowsversion().build < 19041,
                    reason="needs the real DWM of Windows 10 2004+")
def test_the_real_dwm_accepts_and_keeps_the_dark_flag(root, monkeypatch) -> None:
    monkeypatch.delenv(wc.ENV_KILL_SWITCH, raising=False)
    assert wc.enabled()
    results = wc.apply(root, "dark")
    assert results.get(20) == 0, results
    native = wc._native()
    hwnd = wc.window_handle(root, native)
    hresult, value = native.get_attribute(hwnd, 20)
    assert (hresult, value) == (0, 1)
    wc.apply(root, "light")
    assert native.get_attribute(hwnd, 20) == (0, 0)
