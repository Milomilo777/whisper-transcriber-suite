"""Closing the window ends the app; the main loop and Tk callbacks never die silently.

* ``App.destroy`` used to cancel every pending ``after()`` through the root's
  ``after_cancel``, which also deletes the callback's Tcl command. A widget that
  runs its own ``after()`` loop (the scrollable tab page's canvas) still listed that
  command, so its ``destroy()`` raised ``TclError: can't delete Tcl command``, the root
  was never destroyed and the process kept running behind a half-empty window.
* ``App.loop()`` re-armed its 500 ms ``after()`` only when every step succeeded, so one
  exception stopped the queue pump for the rest of the session.
* Tk callback errors went to ``sys.stderr``, which is ``None`` under pythonw.

The destroy tests build a real Tk root of class ``App`` without running
``App.__init__`` (no services, no config), so the real ``App.destroy`` runs.
"""
from __future__ import annotations

import logging
import sys
import tkinter as tk
import types
from typing import Any

import pytest

from app import app as app_module
from app.app import App


def _bare_app() -> App:
    """A real Tk root whose class is App, without App.__init__."""
    root = App.__new__(App)
    tk.Tk.__init__(root)
    root.withdraw()
    return root


def _pending(root: tk.Misc) -> tuple[str, ...]:
    return tuple(root.tk.splitlist(root.tk.call("after", "info")))


def test_destroy_survives_a_child_that_keeps_its_own_after_loop() -> None:
    root = _bare_app()
    canvas = tk.Canvas(root)
    canvas.pack()

    def _poll() -> None:
        canvas.after(400, _poll)

    canvas.after(50, _poll)
    root.after(60_000, lambda: None)
    root.update()

    root.destroy()  # used to raise TclError("can't delete Tcl command")

    assert getattr(canvas, "_tclCommands") is None  # the canvas really was torn down
    with pytest.raises(tk.TclError):
        root.winfo_exists()  # and so was the root


def test_cancel_pending_after_callbacks_leaves_owners_commands_alone() -> None:
    root = tk.Tk()
    try:
        root.withdraw()
        canvas = tk.Canvas(root)
        canvas.after(60_000, lambda: None)
        root.after(60_000, lambda: None)
        root.after_idle(lambda: None)
        commands_before = list(getattr(canvas, "_tclCommands") or [])

        app_module.cancel_pending_after_callbacks(root)

        assert _pending(root) == ()
        # The command still belongs to the canvas, so its own destroy deletes it.
        assert list(getattr(canvas, "_tclCommands") or []) == commands_before
        canvas.destroy()
    finally:
        root.destroy()


def test_destroy_ends_the_event_loop_even_if_teardown_fails(monkeypatch: Any) -> None:
    root = _bare_app()
    child = tk.Frame(root)
    calls: list[str] = []

    def _broken_destroy() -> None:
        raise tk.TclError("simulated teardown failure")

    monkeypatch.setattr(child, "destroy", _broken_destroy)
    monkeypatch.setattr(root, "quit", lambda: calls.append("quit"))
    try:
        root.destroy()
        assert calls == ["quit"], "a failed teardown must still end mainloop"
    finally:
        monkeypatch.undo()
        tk.Tk.destroy(root)


# --------------------------------------------------------------------- App.loop()


def _loop_self(**services: Any) -> types.SimpleNamespace:
    scheduled: list[tuple[int, Any]] = []
    ns = types.SimpleNamespace(
        _closing=False,
        scheduled=scheduled,
        after=lambda ms, fn: scheduled.append((ms, fn)),
        refresh=services.get("refresh", lambda: None),
        transcription_service=types.SimpleNamespace(
            dispatch_waiting=services.get("dispatch", lambda: None)),
        download_service=types.SimpleNamespace(
            process_queue=services.get("downloads", lambda: None)),
        _loop_errors={},
    )
    ns.loop = lambda: None
    ns._log_loop_error = lambda step, error: App._log_loop_error(ns, step, error)  # type: ignore[arg-type]
    return ns


def test_loop_rearms_and_logs_when_a_step_raises(caplog: Any) -> None:
    ran: list[str] = []

    def _boom() -> None:
        raise OSError("worker exe blocked")

    fake = _loop_self(dispatch=_boom, downloads=lambda: ran.append("downloads"))
    with caplog.at_level(logging.ERROR, logger="app.app"):
        App.loop(fake)  # type: ignore[arg-type]

    assert [ms for ms, _fn in fake.scheduled] == [500]
    assert ran == ["downloads"], "one failing step must not skip the others"
    assert "worker exe blocked" in caplog.text


def test_loop_logs_a_repeating_error_once(caplog: Any) -> None:
    def _boom() -> None:
        raise OSError("still blocked")

    fake = _loop_self(refresh=_boom)
    with caplog.at_level(logging.ERROR, logger="app.app"):
        for _ in range(5):
            App.loop(fake)  # type: ignore[arg-type]

    assert len(fake.scheduled) == 5
    errors = [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len(errors) == 1


def test_loop_does_not_rearm_once_closing_started_during_a_step() -> None:
    fake = _loop_self()

    def _close() -> None:
        fake._closing = True

    fake.download_service.process_queue = _close
    App.loop(fake)  # type: ignore[arg-type]

    assert fake.scheduled == []


# ----------------------------------------------------- Tk callback exceptions


def test_tk_callback_errors_go_to_the_log_and_the_console(caplog: Any) -> None:
    shown: list[str] = []
    fake = types.SimpleNamespace(log=shown.append, _last_callback_error="")
    try:
        raise ValueError("bad value in a button handler")
    except ValueError:
        exc_info = sys.exc_info()

    with caplog.at_level(logging.ERROR, logger="app.app"):
        App.report_callback_exception(fake, *exc_info)  # type: ignore[arg-type]
        App.report_callback_exception(fake, *exc_info)  # type: ignore[arg-type]

    assert "bad value in a button handler" in caplog.text
    assert "Traceback" in caplog.text
    assert len(shown) == 1, "the same error is shown once, not once per repeat"
    assert "bad value in a button handler" in shown[0]


def test_tk_callback_error_report_survives_a_broken_console(caplog: Any) -> None:
    def _broken_log(_msg: str) -> None:
        raise tk.TclError("console already destroyed")

    fake = types.SimpleNamespace(log=_broken_log, _last_callback_error="")
    try:
        raise KeyError("x")
    except KeyError:
        exc_info = sys.exc_info()

    with caplog.at_level(logging.ERROR, logger="app.app"):
        App.report_callback_exception(fake, *exc_info)  # type: ignore[arg-type]

    assert "KeyError" in caplog.text


def test_a_real_tk_callback_error_reaches_report_callback_exception(caplog: Any) -> None:
    root = _bare_app()
    root._last_callback_error = ""  # type: ignore[attr-defined]
    root.log = lambda _msg: None  # type: ignore[attr-defined]

    def _handler() -> None:
        raise RuntimeError("raised inside an after() callback")

    try:
        with caplog.at_level(logging.ERROR, logger="app.app"):
            root.after(0, _handler)
            root.update()
        assert "raised inside an after() callback" in caplog.text
    finally:
        root.destroy()


# ------------------------------------------------------------- on_exit order


def test_on_exit_hides_the_window_before_stopping_workers(monkeypatch: Any) -> None:
    order: list[str] = []
    monkeypatch.setattr(app_module, "stop_live_session", lambda _app: order.append("live"))
    monkeypatch.setattr(app_module, "stop_voice_clone_worker",
                        lambda _app: order.append("voice"))
    fake = types.SimpleNamespace(
        _exit_from_tray=True,
        app_config={},
        tray=None,
        queue=[],
        download_queue=[],
        _closing=False,
        _folder_watcher=None,
        history=None,
        _save_window_geometry=lambda: order.append("geometry"),
        withdraw=lambda: order.append("withdraw"),
        _shutdown_server_on_exit=lambda: order.append("server"),
        transcription_service=types.SimpleNamespace(
            stop_all=lambda: order.append("workers")),
        destroy=lambda: order.append("destroy"),
    )

    App.on_exit(fake)  # type: ignore[arg-type]

    assert order.index("geometry") < order.index("withdraw")
    assert order.index("withdraw") < min(order.index(s) for s in ("live", "voice", "server", "workers"))
    assert order[-1] == "destroy"
