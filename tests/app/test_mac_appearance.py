"""macOS window appearance (``app/theme/mac_appearance.py``): the title bar follows the theme mode.

The Tk windowing system here is win32 or x11, so the tests pretend to be Aqua by patching
``mac_native.is_aqua`` and stand in for Tk's ``::tk::unsupported::MacWindowStyle`` with a Tcl
procedure that records its arguments. What Tk and macOS really do with ``appearance`` (and
whether ``isdark`` follows it) is checked in the macOS VM, not here.
"""
from __future__ import annotations

import inspect
import logging
import tkinter as tk
from typing import Any

import pytest

from app import mac_native
from app.theme import mac_appearance as ma

_CMD = "::tk::unsupported::MacWindowStyle"


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    r.withdraw()
    yield r
    r.destroy()


@pytest.fixture
def aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: True)
    monkeypatch.delenv(ma.win_chrome.ENV_KILL_SWITCH, raising=False)


def _fake_style(root: tk.Misc, body: str | None = None) -> None:
    """Define the Tcl command Aqua Tk has; it appends its arguments to ``::g1calls``."""
    root.tk.eval("set ::g1calls {}")
    root.tk.eval("namespace eval ::tk::unsupported {}")
    root.tk.eval(f"proc {_CMD} {{args}} {{ {body or 'lappend ::g1calls $args'} }}")


def _calls(root: tk.Misc) -> list[tuple[str, ...]]:
    raw = root.tk.splitlist(root.tk.eval("set ::g1calls"))
    return [tuple(root.tk.splitlist(item)) for item in raw]


def _dialog(root: tk.Misc, *, override: bool = False) -> tk.Toplevel:
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


# ------------------------------------------------------------------ the mode -> word

@pytest.mark.parametrize("mode, word", [
    ("light", "aqua"), ("dark", "darkaqua"), ("system", "auto"), ("nonsense", "darkaqua"),
])
def test_each_theme_mode_has_its_tk_appearance(mode: str, word: str) -> None:
    assert ma.appearance_for(mode) == word


# ------------------------------------------------------------------------------ apply

@pytest.mark.parametrize("mode, word", [("light", "aqua"), ("dark", "darkaqua"), ("system", "auto")])
def test_apply_sets_the_windows_appearance(root, aqua, mode: str, word: str) -> None:
    _fake_style(root)
    assert ma.apply(root, mode) is True
    assert _calls(root) == [("appearance", ".", word)]


def test_apply_names_the_dialog_it_themes(root, aqua) -> None:
    _fake_style(root)
    dlg = _dialog(root)
    assert ma.apply(dlg, "dark") is True
    assert _calls(root) == [("appearance", str(dlg), "darkaqua")]


@pytest.mark.parametrize("system", ["win32", "x11"])
def test_nothing_happens_off_macos(root, monkeypatch: pytest.MonkeyPatch, system: str) -> None:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)
    _fake_style(root)
    ma.install(root, "dark")
    assert ma.apply(root, "dark") is False
    assert ma.apply_all(root, "dark") == 0
    _show(_dialog(root))
    assert _calls(root) == []


def test_the_config_switch_turns_every_call_off(root, aqua) -> None:
    _fake_style(root)
    ma.set_enabled(False)
    ma.install(root, "dark")
    assert ma.apply(root, "dark") is False
    assert _calls(root) == []


@pytest.mark.parametrize("value", ["false", "0", "off", ""])
def test_a_hand_edited_off_string_counts_as_off(root, aqua, value: str) -> None:
    ma.set_enabled(value)
    assert ma.enabled() is False


def test_the_environment_switch_turns_every_call_off(root, aqua, monkeypatch) -> None:
    _fake_style(root)
    monkeypatch.setenv(ma.win_chrome.ENV_KILL_SWITCH, "1")
    assert ma.apply(root, "dark") is False
    assert _calls(root) == []


def test_a_tk_without_the_option_is_ignored_and_logged_once(
    root, aqua, caplog: pytest.LogCaptureFixture,
) -> None:
    _fake_style(root, 'error "bad option \\"appearance\\""')
    with caplog.at_level(logging.INFO, logger=ma.logger.name):
        assert ma.apply(root, "dark") is False
        assert ma.apply(root, "light") is False
    assert [r.getMessage() for r in caplog.records].count(
        'Could not set the window appearance: bad option "appearance"') == 1


# ------------------------------------------------------------------ every window, later

def test_apply_all_sets_the_root_and_every_open_dialog(root, aqua) -> None:
    _fake_style(root)
    first = _dialog(root)
    nested = tk.Toplevel(first)
    nested.withdraw()
    assert ma.apply_all(root, "dark") == 3
    assert {c[1] for c in _calls(root)} == {".", str(first), str(nested)}
    assert {c[2] for c in _calls(root)} == {"darkaqua"}


def test_apply_all_skips_windows_without_a_title_bar(root, aqua) -> None:
    _fake_style(root)
    _dialog(root, override=True)     # a tooltip
    assert ma.apply_all(root, "light") == 1
    assert _calls(root) == [("appearance", ".", "aqua")]


def test_a_dialog_opened_later_gets_the_current_mode_when_shown(root, aqua) -> None:
    _fake_style(root)
    ma.install(root, "dark")
    assert _calls(root) == [("appearance", ".", "darkaqua")]
    dlg = _dialog(root)
    _show(dlg)
    assert ("appearance", str(dlg), "darkaqua") in _calls(root)
    ma.apply_all(root, "light")
    later = _dialog(root)
    _show(later)
    assert ("appearance", str(later), "aqua") in _calls(root)


def test_a_dialog_that_is_shown_again_is_not_touched_again(root, aqua) -> None:
    _fake_style(root)
    ma.install(root, "dark")
    dlg = _dialog(root)
    _show(dlg)
    before = len(_calls(root))
    _show(dlg)    # minimise and restore
    assert len(_calls(root)) == before


def test_a_tooltip_shown_later_is_left_alone(root, aqua) -> None:
    _fake_style(root)
    ma.install(root, "dark")
    tip = _dialog(root, override=True)
    _show(tip)
    assert all(c[1] != str(tip) for c in _calls(root))


def test_a_destroyed_dialog_leaves_nothing_behind(root, aqua) -> None:
    _fake_style(root)
    ma.install(root, "dark")
    dlg = _dialog(root)
    _show(dlg)
    dlg.destroy()
    assert ma.apply_all(root, "light") == 1


def test_install_twice_binds_once(root, aqua) -> None:
    _fake_style(root)
    ma.install(root, "dark")
    ma.install(root, "dark")
    dlg = _dialog(root)
    _show(dlg)
    assert [c for c in _calls(root) if c[1] == str(dlg)] == [("appearance", str(dlg), "darkaqua")]


def test_reset_for_tests_restores_the_defaults() -> None:
    ma.set_enabled(False)
    ma._mode = "dark"
    ma._failed.add("x")
    ma.reset_for_tests()
    assert ma._config_enabled is True and ma._mode == "system" and ma._failed == set()


# ------------------------------------------------------------------------ the app wiring

def test_the_app_sets_the_mode_before_it_resolves_it() -> None:
    """With the root pinned to darkaqua Tk's isdark says dark: System must be set to auto first."""
    from app.app import App

    init = inspect.getsource(App.__init__)
    assert (0 < init.find("mac_appearance.install(self, self.theme_var.get())")
            < init.find("start_theme = _resolve_theme(self.theme_var.get())"))
    restyle = inspect.getsource(App._restyle)
    assert 0 <= restyle.find("mac_appearance.apply_all(self, name)") < restyle.find("_resolve_theme(name)")
    assert "mac_appearance.set_enabled(" in init


def test_a_theme_switch_pins_the_windows_then_resolves(
    root, aqua, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """App._restyle: the appearance call comes first, so "system" reads an unpinned window."""
    pytest.importorskip("sv_ttk")
    from app import app as app_module

    _fake_style(root)
    events: list[Any] = []

    def resolve(name: str) -> str:
        events.append(("resolve", name, list(_calls(root))))
        return "dark" if name == "dark" else "light"

    monkeypatch.setattr(app_module, "_resolve_theme", resolve)
    app_module.App._restyle(root, "system")   # type: ignore[arg-type]  # duck-typed host
    assert events == [("resolve", "system", [("appearance", ".", "auto")])]
    app_module.App._restyle(root, "dark")     # type: ignore[arg-type]
    assert _calls(root)[-1] == ("appearance", ".", "darkaqua")
