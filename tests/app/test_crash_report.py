"""Uncaught errors in the GUI process reach the app log and the user.

Under pythonw ``sys.stderr`` is ``None``, so a crash while the main window is built (an
exception out of ``App.__init__``) used to leave no trace and no message at all.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import pytest

import app as app_pkg
from app import crash_report


def _exc_info(exc: BaseException) -> tuple[type[BaseException], BaseException, Any]:
    try:
        raise exc
    except BaseException:  # noqa: BLE001 - capturing the test's own exception
        info = sys.exc_info()
    assert info[0] is not None and info[1] is not None
    return info[0], info[1], info[2]


def test_the_hook_logs_the_traceback_and_tells_the_user(monkeypatch: Any, caplog: Any) -> None:
    previous: list[type[BaseException]] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: previous.append(t))
    shown: list[str] = []
    crash_report.install_excepthook(notify=shown.append)

    with caplog.at_level(logging.ERROR):
        sys.excepthook(*_exc_info(RuntimeError("window could not be built")))

    assert "window could not be built" in caplog.text
    assert "Traceback" in caplog.text
    assert len(shown) == 1 and "window could not be built" in shown[0]
    assert previous == [RuntimeError], "the previous hook still runs"


def test_ctrl_c_is_not_reported_as_a_crash(monkeypatch: Any, caplog: Any) -> None:
    previous: list[type[BaseException]] = []
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: previous.append(t))
    shown: list[str] = []
    crash_report.install_excepthook(notify=shown.append)

    with caplog.at_level(logging.ERROR):
        sys.excepthook(*_exc_info(KeyboardInterrupt()))

    assert shown == []
    assert caplog.text == ""
    assert previous == [KeyboardInterrupt]


def test_a_failing_notice_does_not_hide_the_error(monkeypatch: Any, caplog: Any) -> None:
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: None)

    def _no_display(_msg: str) -> None:
        raise RuntimeError("no display")

    crash_report.install_excepthook(notify=_no_display)
    with caplog.at_level(logging.ERROR):
        sys.excepthook(*_exc_info(ValueError("original error")))

    assert "original error" in caplog.text


def test_the_hook_opens_the_log_file_when_logging_is_not_set_up_yet(monkeypatch: Any) -> None:
    monkeypatch.setattr(sys, "excepthook", lambda t, v, tb: None)
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    calls: list[str] = []
    import core.logging_setup as logging_setup
    monkeypatch.setattr(logging_setup, "setup_logging", lambda *a, **k: calls.append("setup"))
    crash_report.install_excepthook(notify=lambda _m: None)

    sys.excepthook(*_exc_info(OSError("config folder unreadable")))

    assert calls == ["setup"]


def test_run_installs_the_hook_before_building_the_window(monkeypatch: Any) -> None:
    import app.app as app_module
    import app.dpi as dpi
    from core import offline

    monkeypatch.setattr(dpi, "enable_dpi_awareness", lambda: None)
    monkeypatch.setattr(offline, "install_network_guard", lambda: None)
    installed: list[str] = []
    monkeypatch.setattr(crash_report, "install_excepthook",
                        lambda *a, **k: installed.append("hook"))

    class _Boom:
        def __init__(self) -> None:
            assert installed == ["hook"], "the hook must be in place before App()"
            raise RuntimeError("App.__init__ failed")

    monkeypatch.setattr(app_module, "App", _Boom)
    with pytest.raises(RuntimeError, match="App.__init__ failed"):
        app_pkg.run()
