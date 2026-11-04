"""Hermetic tests for SystemExit handling in app.crash_report.install_excepthook."""
from __future__ import annotations

import logging
import sys

import pytest

from app import crash_report


def test_excepthook_ignores_system_exit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    notified: list[str] = []
    previous_calls: list[tuple[type[BaseException], BaseException]] = []

    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda exc_type, exc, tb: previous_calls.append((exc_type, exc)),
    )
    monkeypatch.setattr(crash_report, "_ensure_log_file", lambda: None)

    crash_report.install_excepthook(notify=notified.append)
    caplog.set_level(logging.CRITICAL, logger=crash_report.__name__)

    for code in (0, 1, None, "clean exit"):
        exc = SystemExit(code)
        sys.excepthook(SystemExit, exc, None)

    assert notified == [], f"SystemExit should not notify user, got: {notified!r}"
    assert caplog.records == []
    assert len(previous_calls) == 4


def test_excepthook_ignores_custom_system_exit_subclass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CustomExit(SystemExit):
        pass

    notified: list[str] = []
    monkeypatch.setattr(sys, "excepthook", lambda exc_type, exc, tb: None)
    monkeypatch.setattr(crash_report, "_ensure_log_file", lambda: None)

    crash_report.install_excepthook(notify=notified.append)
    sys.excepthook(_CustomExit, _CustomExit(2), None)
    assert notified == []


def test_excepthook_ignores_keyboard_interrupt_and_reports_runtime_error(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    notified: list[str] = []
    previous_calls: list[tuple[type[BaseException], BaseException]] = []

    monkeypatch.setattr(
        sys,
        "excepthook",
        lambda exc_type, exc, tb: previous_calls.append((exc_type, exc)),
    )
    monkeypatch.setattr(crash_report, "_ensure_log_file", lambda: None)
    monkeypatch.setattr(
        crash_report, "_log_folder", lambda: "C:\\Users\\टेस्ट\\AppData\\Local\\Logs"
    )

    crash_report.install_excepthook(notify=notified.append)
    caplog.set_level(logging.CRITICAL, logger=crash_report.__name__)

    kb = KeyboardInterrupt()
    sys.excepthook(KeyboardInterrupt, kb, None)
    assert notified == []

    boom = RuntimeError("boom")
    sys.excepthook(RuntimeError, boom, None)
    assert len(notified) == 1
    assert "RuntimeError: boom" in notified[0]
    assert "C:\\Users\\टेस्ट\\AppData\\Local\\Logs" in notified[0]
    assert len(caplog.records) == 1
    assert previous_calls == [(KeyboardInterrupt, kb), (RuntimeError, boom)]
