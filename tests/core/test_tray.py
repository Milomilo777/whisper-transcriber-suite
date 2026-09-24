"""Tests for the system-tray controller helpers."""
from __future__ import annotations

import sys
import types

import pytest


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


def test_tray_is_unsupported_on_macos_even_with_the_libraries(monkeypatch):
    """pystray's AppKit backend needs the main thread, which Tk owns, so the
    tray is off on macOS (the app lives in the Dock)."""
    from app.widgets import tray as tray_mod

    monkeypatch.setattr(tray_mod, "_try_load_pystray", lambda: (object(), object()))
    monkeypatch.setattr(sys, "platform", "darwin")
    c = tray_mod.TrayController(types.SimpleNamespace(post_to_main=lambda fn: None))  # type: ignore[arg-type]
    assert c.is_supported() is False
