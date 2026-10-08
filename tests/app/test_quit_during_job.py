"""Quitting with a job running: macOS Cmd+Q, the reason on file, the resume wording.

* Tk's default ``::tk::mac::Quit`` (Cmd+Q, app-menu Quit, Dock Quit) exits the process at
  once, so a running transcription was lost with no question. The App now owns that
  command and routes it through the same exit path as File -> Exit / Ctrl+Q.
* A confirmed exit marks the running history rows as closed on purpose, so the next launch
  does not call them "a crash".
* The resume prompt words itself after what actually happened.
"""
from __future__ import annotations

import tkinter as tk
import types
from pathlib import Path
from typing import Any

import pytest

from app import app as app_module
from app.app import App
from core.history import EXIT_REASON, HistoryDB


def _bare_app() -> App:
    """A real Tk root whose class is App, without App.__init__."""
    root = App.__new__(App)
    tk.Tk.__init__(root)
    root.withdraw()
    return root


# --------------------------------------------------------- Cmd+Q wiring


def test_aqua_registers_the_mac_quit_command_on_the_force_exit_path() -> None:
    created: dict[str, Any] = {}
    fake = types.SimpleNamespace(
        tk=types.SimpleNamespace(call=lambda *a: "aqua"),
        createcommand=lambda name, fn: created.__setitem__(name, fn),
        _force_exit=lambda: created.setdefault("exit_calls", []).append(1),
    )
    App._install_quit_handler(fake)  # type: ignore[arg-type]

    assert "::tk::mac::Quit" in created
    created["::tk::mac::Quit"]()
    assert created["exit_calls"] == [1]


@pytest.mark.parametrize("system", ["win32", "x11"])
def test_other_windowing_systems_register_nothing(system: str) -> None:
    created: dict[str, Any] = {}
    fake = types.SimpleNamespace(
        tk=types.SimpleNamespace(call=lambda *a: system),
        createcommand=lambda name, fn: created.__setitem__(name, fn),
        _force_exit=lambda: None,
    )
    App._install_quit_handler(fake)  # type: ignore[arg-type]
    assert created == {}


def test_a_failing_windowing_query_is_not_fatal() -> None:
    def _boom(*_a: Any) -> str:
        raise tk.TclError("no display")

    fake = types.SimpleNamespace(
        tk=types.SimpleNamespace(call=_boom),
        createcommand=lambda *_a: pytest.fail("must not register"),
        _force_exit=lambda: None,
    )
    App._install_quit_handler(fake)  # type: ignore[arg-type]


def test_the_tcl_quit_command_reaches_force_exit_on_a_real_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _bare_app()
    calls: list[str] = []
    try:
        monkeypatch.setattr(App, "_force_exit", lambda self: calls.append("exit"))
        # Pretend to be Aqua: the real windowing system here is win32/x11.
        real_call = root.tk.call

        class _Tk:
            def __getattr__(self, name: str) -> Any:
                return getattr(root.tk, name)

            def call(self, *args: Any) -> Any:
                if args == ("tk", "windowingsystem"):
                    return "aqua"
                return real_call(*args)

        proxy = types.SimpleNamespace(
            tk=_Tk(), createcommand=root.createcommand, _force_exit=root._force_exit,
        )
        App._install_quit_handler(proxy)  # type: ignore[arg-type]
        root.tk.call("::tk::mac::Quit")  # what Cmd+Q makes Tk run
        assert calls == ["exit"]
    finally:
        root.destroy()


# ------------------------------------------------ on_exit re-entrancy and reason


def _exit_fake(history: Any, tasks: list[Any], calls: list[str]) -> types.SimpleNamespace:
    ns = types.SimpleNamespace(
        _exit_from_tray=True, app_config={}, tray=None, queue=tasks,
        download_queue=[], _closing=False, _folder_watcher=None, history=history,
        withdraw=lambda: None, destroy=lambda: calls.append("destroy"),
        _save_window_geometry=lambda: None,
        _shutdown_server_on_exit=lambda: None,
        transcription_service=types.SimpleNamespace(
            stop_all=lambda **_k: calls.append("stop_all")),
    )
    return ns


def _patch_teardown(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: True)
    monkeypatch.setattr(app_module, "stop_live_session", lambda _a: None)
    monkeypatch.setattr(app_module, "stop_voice_clone_worker", lambda _a: None)


def test_a_confirmed_exit_marks_the_running_job_as_closed_on_purpose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_teardown(monkeypatch)
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_a, **_k: True)
    db = HistoryDB(tmp_path / "history.db")
    rid = db.insert_transcription(str(tmp_path / "a.wav"))
    other = db.insert_transcription(str(tmp_path / "b.wav"))  # not in this app's queue
    calls: list[str] = []
    task = types.SimpleNamespace(status="running", process=None, history_id=rid)
    fake = _exit_fake(db, [task], calls)

    App.on_exit(fake)  # type: ignore[arg-type]

    rows = {r["id"]: r for r in HistoryDB(tmp_path / "history.db").list_transcriptions()}
    assert rows[rid]["status"] == "interrupted" and rows[rid]["error"] == EXIT_REASON
    assert rows[other]["status"] == "running"  # only this app's own jobs are touched
    assert calls == ["stop_all", "destroy"]


def test_a_declined_exit_leaves_the_history_row_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_teardown(monkeypatch)
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_a, **_k: False)
    db = HistoryDB(tmp_path / "history.db")
    rid = db.insert_transcription(str(tmp_path / "a.wav"))
    calls: list[str] = []
    fake = _exit_fake(
        db, [types.SimpleNamespace(status="running", process=None, history_id=rid)], calls)

    App.on_exit(fake)  # type: ignore[arg-type]

    assert db.list_transcriptions()[0]["status"] == "running"
    assert calls == []


def test_a_second_quit_while_the_question_is_open_is_ignored(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cmd+Q pressed again while the dialog is up must not stack a second dialog."""
    _patch_teardown(monkeypatch)
    asked: list[int] = []
    fake = _exit_fake(None, [types.SimpleNamespace(status="running", process=None)], [])

    def _ask(*_a: Any, **_k: Any) -> bool:
        asked.append(1)
        App.on_exit(fake)  # type: ignore[arg-type]  # the nested Cmd+Q
        return False

    monkeypatch.setattr(app_module.messagebox, "askyesno", _ask)
    App.on_exit(fake)  # type: ignore[arg-type]
    assert asked == [1]
    assert getattr(fake, "_exit_prompt_open", False) is False  # released afterwards


# ------------------------------------------------------------ history + wording


def test_history_marks_only_running_rows_of_the_given_ids(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    a = db.insert_transcription("a.wav")
    b = db.insert_transcription("b.wav")
    done = db.insert_transcription("c.wav")
    db.finish_transcription(done, "finished")
    assert db.mark_transcriptions_closed_by_user([a, done, 0]) == 1
    rows = {r["id"]: r for r in db.list_transcriptions()}
    assert rows[a]["status"] == "interrupted" and rows[a]["error"] == EXIT_REASON
    assert rows[b]["status"] == "running"
    assert rows[done]["status"] == "finished" and rows[done]["error"] != EXIT_REASON
    assert db.mark_transcriptions_closed_by_user([]) == 0


def test_the_closed_row_survives_the_launch_sweep_with_its_reason(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    rid = db.insert_transcription("a.wav")
    db.mark_transcriptions_closed_by_user([rid])
    crash = db.insert_transcription("b.wav")  # a real crash leaves 'running'
    db.mark_interrupted()
    rows = {r["id"]: r for r in db.list_transcriptions()}
    assert rows[rid]["error"] == EXIT_REASON
    assert rows[crash]["status"] == "interrupted" and not rows[crash]["error"]


@pytest.mark.parametrize(
    ("errors", "needle", "absent"),
    [
        ([EXIT_REASON], "interrupted when the app was closed", "crash"),
        ([None], "interrupted by a previous crash", "closed"),
        ([""], "interrupted by a previous crash", "closed"),
        ([EXIT_REASON, None], "interrupted the last time the app ran", "crash"),
    ],
)
def test_resume_wording_follows_the_reason(
    errors: list[str | None], needle: str, absent: str,
) -> None:
    rows = [{"error": e} for e in errors]
    text = app_module._resume_prompt_text(rows)
    assert needle in text
    assert absent not in text
    assert text.rstrip().endswith("now?")


def test_resume_wording_pluralises() -> None:
    one = app_module._resume_prompt_text([{"error": EXIT_REASON}])
    two = app_module._resume_prompt_text([{"error": EXIT_REASON}, {"error": EXIT_REASON}])
    assert "1 transcription that was" in one and "Resume it now?" in one
    assert "2 transcriptions that were" in two and "Resume them now?" in two
