"""The macOS microphone notice (``app/dialogs/mac_permission.py``) and its Live tab wiring.

The platform and the permission state are faked; what macOS really shows is proved in the Ventura
VM by ``tools/mac_mic_permission_probe.py``. Every macOS case has a twin showing Windows and Linux
never see the notice.
"""
from __future__ import annotations

import types
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

from app import mac_permissions as mp  # noqa: E402
from app.dialogs import mac_permission  # noqa: E402
from app.widgets import live_tab  # noqa: E402


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:  # pragma: no cover — headless CI without a display
        pytest.skip("no Tk display available")
    r.withdraw()
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def _buttons(widget: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            found[str(child.cget("text"))] = child
        found.update(_buttons(child))
    return found


# ------------------------------------------------------------------ the dialog


def test_blocked_notice_has_open_settings_button_that_opens_the_pane(root) -> None:
    opened: list[str] = []
    dialog = mac_permission.build_mic_notice(
        root, mp.REASON_BLOCKED, opener=lambda: opened.append("x") or True)
    buttons = _buttons(dialog)
    assert "Open System Settings" in buttons and "Close" in buttons
    buttons["Open System Settings"].invoke()
    assert opened == ["x"]
    assert not dialog.winfo_exists()


def test_close_button_does_not_open_settings(root) -> None:
    opened: list[str] = []
    dialog = mac_permission.build_mic_notice(
        root, mp.REASON_BLOCKED, opener=lambda: opened.append("x") or True)
    _buttons(dialog)["Close"].invoke()
    assert opened == []
    assert not dialog.winfo_exists()


def test_first_use_notice_only_explains(root) -> None:
    dialog = mac_permission.build_mic_notice(
        root, mp.REASON_FIRST_USE, opener=lambda: pytest.fail("opened settings before asking"))
    buttons = _buttons(dialog)
    assert "Open System Settings" not in buttons
    buttons["Close"].invoke()
    assert not dialog.winfo_exists()


def test_the_two_reasons_say_different_things(root) -> None:
    def texts(reason: str) -> str:
        dialog = mac_permission.build_mic_notice(root, reason, opener=lambda: True)
        out = " ".join(str(w.cget("text")) for w in _all(dialog) if isinstance(w, ttk.Label))
        dialog.destroy()
        return out

    assert texts(mp.REASON_FIRST_USE) != texts(mp.REASON_BLOCKED)


def _all(widget: Any) -> list[Any]:
    out = [widget]
    for child in widget.winfo_children():
        out.extend(_all(child))
    return out


# ------------------------------------------------------------- Live tab wiring


@pytest.fixture
def app(root):
    a = types.SimpleNamespace()
    a.app_config = {}
    a.logged: list[str] = []
    a.log = a.logged.append
    a.after = root.after
    return a


@pytest.fixture
def shown(monkeypatch):
    calls: list[str] = []

    def fake_show(_master: Any, reason: str, **_kw: Any) -> bool:
        calls.append(reason)
        return False

    monkeypatch.setattr(live_tab, "show_mic_notice", fake_show)
    monkeypatch.setattr(live_tab, "_remember_mac_notice", lambda a: a.app_config.update(
        {live_tab._MAC_NOTICE_KEY: True}))
    return calls


def _mac(monkeypatch, status: str) -> None:
    monkeypatch.setattr(mp, "is_macos", lambda: True)
    monkeypatch.setattr(mp, "microphone_status", lambda: status)


def test_gate_denied_blocks_the_start_and_explains(app, shown, monkeypatch) -> None:
    _mac(monkeypatch, mp.DENIED)
    assert live_tab._mac_mic_gate(app, "mic") is False
    assert shown == [mp.REASON_BLOCKED]


def test_gate_first_use_explains_once_then_lets_the_start_go_on(app, shown, monkeypatch) -> None:
    _mac(monkeypatch, mp.NOT_DETERMINED)
    assert live_tab._mac_mic_gate(app, "mic") is True
    assert shown == [mp.REASON_FIRST_USE]
    assert app.app_config.get(live_tab._MAC_NOTICE_KEY) is True
    assert live_tab._mac_mic_gate(app, "mic") is True
    assert shown == [mp.REASON_FIRST_USE]  # not again


def test_gate_authorized_is_silent(app, shown, monkeypatch) -> None:
    _mac(monkeypatch, mp.AUTHORIZED)
    assert live_tab._mac_mic_gate(app, "mic") is True
    assert shown == []


def test_gate_ignores_system_audio(app, shown, monkeypatch) -> None:
    _mac(monkeypatch, mp.DENIED)
    assert live_tab._mac_mic_gate(app, "loopback") is True
    assert shown == []


@pytest.mark.parametrize("status", [mp.DENIED, mp.NOT_DETERMINED, mp.UNKNOWN])
def test_gate_never_shows_off_macos(app, shown, monkeypatch, status: str) -> None:
    monkeypatch.setattr(mp, "is_macos", lambda: False)
    monkeypatch.setattr(mp, "microphone_status", lambda: status)
    assert live_tab._mac_mic_gate(app, "mic") is True
    assert shown == []


def _session(state: str) -> Any:
    return types.SimpleNamespace(
        capture_error=lambda: "", input_signal_state=lambda: state)


def _health_app(app: Any, state: str) -> Any:
    app.live_session = _session(state)
    app.live_transcriber = None
    app.live_status_var = types.SimpleNamespace(set=lambda v: None)
    return app


def test_silence_on_macos_shows_the_notice_once_per_session(app, shown, root, monkeypatch) -> None:
    _mac(monkeypatch, mp.AUTHORIZED)
    _health_app(app, "silent")
    live_tab._check_health(app)
    live_tab._check_health(app)
    root.update()
    assert shown == [mp.REASON_BLOCKED]


def test_silence_off_macos_shows_nothing(app, shown, root, monkeypatch) -> None:
    monkeypatch.setattr(mp, "is_macos", lambda: False)
    _health_app(app, "silent")
    live_tab._check_health(app)
    root.update()
    assert shown == []


def test_no_silence_on_macos_shows_nothing(app, shown, root, monkeypatch) -> None:
    _mac(monkeypatch, mp.AUTHORIZED)
    _health_app(app, "ok")
    live_tab._check_health(app)
    root.update()
    assert shown == []
