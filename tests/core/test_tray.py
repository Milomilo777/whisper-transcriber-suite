"""Tests for the system-tray controller helpers."""
from __future__ import annotations

import sys
import types

import pytest


def test_stop_returns_even_when_the_icon_stop_blocks():
    """stop() runs on every App.destroy(), so it must never hang the exit.

    pystray's Xorg backend can block inside icon.stop() while its loop
    thread holds the X display (no system tray, docking never finishes);
    Linux CI timed out in App.destroy() exactly there.
    """
    import threading

    from app.widgets import tray as tray_mod

    release = threading.Event()

    class _BlockingIcon:
        def stop(self):
            release.wait(30)

    fake_app = types.SimpleNamespace(post_to_main=lambda fn: None)
    c = tray_mod.TrayController(fake_app)  # type: ignore[arg-type]
    c._icon = _BlockingIcon()
    caller = threading.Thread(target=c.stop, daemon=True)
    caller.start()
    caller.join(timeout=6)
    try:
        assert not caller.is_alive(), "TrayController.stop() hung on a blocking icon.stop()"
        assert c._icon is None
    finally:
        release.set()


def test_stop_without_wait_returns_at_once_and_still_asks_the_icon_to_stop():
    """App.destroy() uses stop(wait=False): no waiting at all, but the
    icon loop must still be told to end (it holds a reference to the App)."""
    import threading
    import time

    from app.widgets import tray as tray_mod

    asked = threading.Event()
    release = threading.Event()

    class _BlockingIcon:
        def stop(self):
            asked.set()
            release.wait(30)

    fake_app = types.SimpleNamespace(post_to_main=lambda fn: None)
    c = tray_mod.TrayController(fake_app)  # type: ignore[arg-type]
    c._icon = _BlockingIcon()
    t0 = time.monotonic()
    try:
        c.stop(wait=False)
        assert time.monotonic() - t0 < 0.5
        assert c._icon is None
        assert asked.wait(2), "icon.stop() was never called"
    finally:
        release.set()


def test_is_available_returns_false_without_pystray(monkeypatch):
    # Force pystray import to fail.
    monkeypatch.setitem(sys.modules, "pystray", None)
    from app.widgets import tray
    assert tray.is_available() is False
    assert "pystray" in tray.availability_reason()


def test_controller_without_pystray_is_no_op(monkeypatch):
    """If pystray is missing, TrayController.start / stop / set_active
    must not raise."""
    fake_app = types.SimpleNamespace(after=lambda _ms, _fn: None, log=lambda _m: None)
    monkeypatch.setitem(sys.modules, "pystray", None)
    from app.widgets import tray
    c = tray.TrayController(fake_app)  # type: ignore[arg-type]
    assert c.is_supported() is False
    c.start()  # noop
    c.set_active(True)  # noop
    c.notify("title", "body")  # noop
    c.stop()  # noop


def test_build_icon_image_idle_and_active():
    pytest.importorskip("PIL")
    from app.widgets import tray
    idle = tray._build_icon_image(active=False)
    active = tray._build_icon_image(active=True)
    assert idle.size == (64, 64)
    assert active.size == (64, 64)
    # The two images shouldn't be identical (different pixels).
    assert idle.tobytes() != active.tobytes()


def test_failed_start_reports_the_tray_as_unsupported(monkeypatch):
    """If building/starting the icon raises, the controller must stop
    claiming support.

    The App keeps this controller after a failed start(), and its
    minimise-to-tray check only looks at ``is_supported()``. Returning
    True there let the X button withdraw the window with no tray icon to
    restore it — an invisible, stranded process.
    """
    from app.widgets import tray as tray_mod

    class _FakeMenu:
        SEPARATOR = object()

        def __init__(self, *args, **kwargs):
            pass

    class _FailingIcon:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no notification area")

    fake_pystray = types.SimpleNamespace(
        Menu=_FakeMenu,
        MenuItem=lambda *a, **k: None,
        Icon=_FailingIcon,
    )
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (fake_pystray, object()))
    # The tray is disabled on macOS by design (see TrayController.is_supported);
    # this test is about the failed-start logic, so pin a tray platform.
    monkeypatch.setattr(sys, "platform", "win32")

    fake_app = types.SimpleNamespace(post_to_main=lambda fn: None)
    c = tray_mod.TrayController(fake_app)  # type: ignore[arg-type]

    assert c.is_supported() is True  # platform + libs are present...
    c.start()  # ...but the icon cannot be brought up
    assert c._icon is None
    assert c.is_supported() is False


def test_successful_retry_after_a_failed_start_reports_supported(monkeypatch):
    """A transient start failure must stay retryable.

    start() gates on platform/libs support (not the failure flag), so a
    second start() after the notification area appears actually retries;
    success clears the flag and the controller reports supported again.
    """
    from app.widgets import tray as tray_mod

    attempts: list[str] = []

    class _FakeMenu:
        SEPARATOR = object()

        def __init__(self, *args, **kwargs):
            pass

    class _FlakyIcon:
        def __init__(self, *args, **kwargs):
            attempts.append("try")
            if len(attempts) == 1:
                raise RuntimeError("notification area not ready")

    fake_pystray = types.SimpleNamespace(
        Menu=_FakeMenu,
        MenuItem=lambda *a, **k: None,
        Icon=_FlakyIcon,
    )
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (fake_pystray, object()))

    import threading as _threading

    def _fake_safe_thread(fn, name=None):
        # Don't run the icon loop; just hand back a dead thread handle.
        t = _threading.Thread(target=lambda: None, daemon=True)
        return t

    monkeypatch.setattr("core._threads.safe_thread", _fake_safe_thread)
    monkeypatch.setattr(sys, "platform", "win32")  # tray is off on macOS by design

    fake_app = types.SimpleNamespace(post_to_main=lambda fn: None)
    c = tray_mod.TrayController(fake_app)  # type: ignore[arg-type]

    c.start()
    assert c.is_supported() is False  # first attempt failed

    c.start()  # retry once the backend is ready
    assert len(attempts) == 2
    assert c._icon is not None
    assert c.is_supported() is True


def _xorg_pystray(created: list[str]):
    """A fake pystray whose Icon class claims to be the Xorg backend's."""

    class _FakeMenu:
        SEPARATOR = object()

        def __init__(self, *args, **kwargs):
            pass

    class _XorgIcon:
        def __init__(self, *args, **kwargs):
            created.append("icon")

    _XorgIcon.__module__ = "pystray._xorg"
    return types.SimpleNamespace(Menu=_FakeMenu, MenuItem=lambda *a, **k: None, Icon=_XorgIcon)


def _fake_xlib(monkeypatch, owner):
    """Install fake Xlib.display / Xlib.X modules; the tray selection owner is ``owner``."""
    calls: list[str] = []

    class _Display:
        def get_default_screen(self):
            return 0

        def intern_atom(self, name):
            calls.append(name)
            return 42

        def get_selection_owner(self, atom):
            return owner

        def close(self):
            calls.append("close")

    xlib = types.ModuleType("Xlib")
    display_mod = types.ModuleType("Xlib.display")
    display_mod.Display = _Display  # type: ignore[attr-defined]
    x_mod = types.ModuleType("Xlib.X")
    x_mod.NONE = 0  # type: ignore[attr-defined]
    xlib.display = display_mod  # type: ignore[attr-defined]
    xlib.X = x_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "Xlib", xlib)
    monkeypatch.setitem(sys.modules, "Xlib.display", display_mod)
    monkeypatch.setitem(sys.modules, "Xlib.X", x_mod)
    return calls


def _no_loop(monkeypatch):
    import threading as _threading

    monkeypatch.setattr("core._threads.safe_thread",
                        lambda fn, name=None: _threading.Thread(target=lambda: None, daemon=True))


def test_no_x11_system_tray_keeps_the_icon_off(monkeypatch):
    """Xvfb and trayless X11 desktops: pystray's Xorg backend can never dock
    there, and its loop thread left Tk's destroy() hanging on Linux CI (the X
    server stopped answering). No tray owner -> no icon, and minimise-to-tray
    must not hide the window."""
    from app.widgets import tray as tray_mod

    created: list[str] = []
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (_xorg_pystray(created), object()))
    calls = _fake_xlib(monkeypatch, owner=0)
    _no_loop(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    c.start()
    assert created == []
    assert c._icon is None
    assert c.is_supported() is False
    assert calls == ["_NET_SYSTEM_TRAY_S0", "close"]


def test_an_x11_system_tray_lets_the_icon_start(monkeypatch):
    from app.widgets import tray as tray_mod

    created: list[str] = []
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (_xorg_pystray(created), object()))
    _fake_xlib(monkeypatch, owner=types.SimpleNamespace(id=7))
    _no_loop(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    c.start()
    assert created == ["icon"]
    assert c.is_supported() is True


def test_the_tray_check_is_retried_on_the_next_start(monkeypatch):
    """A panel that starts after the app (login) must still get the icon."""
    from app.widgets import tray as tray_mod

    created: list[str] = []
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (_xorg_pystray(created), object()))
    _no_loop(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    _fake_xlib(monkeypatch, owner=0)
    c.start()
    assert c.is_supported() is False
    _fake_xlib(monkeypatch, owner=types.SimpleNamespace(id=7))
    c.start()
    assert created == ["icon"] and c.is_supported() is True


def test_other_backends_skip_the_x11_tray_check(monkeypatch):
    from app.widgets import tray as tray_mod

    created: list[str] = []
    fake = _xorg_pystray(created)
    fake.Icon.__module__ = "pystray._appindicator"
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (fake, object()))
    calls = _fake_xlib(monkeypatch, owner=0)
    _no_loop(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    c.start()
    assert created == ["icon"] and calls == []


def test_an_x11_error_during_the_check_does_not_block_the_icon(monkeypatch):
    """The check only exists to avoid a known hang; if it cannot ask X, behave as before."""
    from app.widgets import tray as tray_mod

    created: list[str] = []
    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (_xorg_pystray(created), object()))
    _fake_xlib(monkeypatch, owner=0)

    def boom(self):
        raise OSError("cannot open display")

    monkeypatch.setattr(sys.modules["Xlib.display"].Display, "__init__", boom)
    _no_loop(monkeypatch)
    monkeypatch.setattr(sys, "platform", "linux")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    c.start()
    assert created == ["icon"]


def test_tray_is_unsupported_on_macos_even_with_the_libraries(monkeypatch):
    """pystray's AppKit backend needs the main thread, which Tk owns, so the
    tray is off on macOS (the app lives in the Dock)."""
    from app.widgets import tray as tray_mod

    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (object(), object()))
    monkeypatch.setattr(sys, "platform", "darwin")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    assert c.is_supported() is False
