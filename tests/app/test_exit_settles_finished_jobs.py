"""A job that finishes while the app is exiting is recorded as finished, not offered for resume.

On a confirmed exit the running rows are marked ``interrupted`` first, then the workers are
stopped (up to a few seconds). A worker that completes inside that window has written its
output files before it sends ``done``, but the app no longer polls events, so the row stayed
``interrupted`` and the next launch offered to transcribe a finished file again. The exit
path now reads the ``done`` events the stopped workers left and finishes those rows. A
cancelled run (the exit sends ``cancel`` first) also ends with ``done``, but without outputs:
it stays ``interrupted`` so its checkpoint is resumed.
"""
from __future__ import annotations

import threading
import time
import types
from pathlib import Path
from queue import Queue
from typing import Any

import pytest

from app import app as app_module
from app.app import App
from app.services.transcription_service import TranscriptionService, task_correlation_id
from core.history import EXIT_REASON, HistoryDB


def _setup(tmp_path: Path, language: str = "fa") -> tuple[
    TranscriptionService, types.SimpleNamespace, HistoryDB, int, Any
]:
    db = HistoryDB(tmp_path / "history.db")
    rid = db.insert_transcription(str(tmp_path / "talk.wav"), language=language)
    db.mark_transcriptions_closed_by_user([rid])  # what on_exit does just before stop_all
    task = types.SimpleNamespace(
        status="running", history_id=rid, file_path=str(tmp_path / "talk.wav"),
        start_time=time.time() - 30, cancelled=False,
    )
    app = types.SimpleNamespace(
        after=lambda _ms, _fn: None, workers=[], worker_events=Queue(), history=db,
        log=lambda _m: None, app_config={},
    )
    app.workers.append({"id": 1, "task": task, "process": None})
    return TranscriptionService(app), app, db, rid, task  # type: ignore[arg-type]


def _done(task: Any, outputs: list[str], **extra: Any) -> dict[str, Any]:
    return {"event": "done", "_worker_id": 1, "task_id": task_correlation_id(task),
            "outputs": outputs, "word_count": 120, "audio_duration": 61.5, **extra}


def _exit(worker_id: int = 1) -> dict[str, Any]:
    return {"event": "worker_exit", "_worker_id": worker_id, "return_code": 0}


def _row(db: HistoryDB, rid: int) -> dict[str, Any]:
    return next(r for r in db.list_transcriptions() if r["id"] == rid)


def _write(path: Path, text: str = "1\n00:00:00,000 --> 00:00:01,000\nhi\n") -> str:
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_a_job_finished_inside_the_stop_window_is_recorded_as_finished(tmp_path: Path) -> None:
    svc, app, db, rid, task = _setup(tmp_path)
    srt = _write(tmp_path / "talk.srt")
    app.worker_events.put(_done(task, [srt]))
    app.worker_events.put(_exit())

    assert svc.settle_done_on_exit(wait_s=2.0) == 1

    row = _row(db, rid)
    assert row["status"] == "finished" and row["error"] == ""
    assert row["output_paths"] == [srt]
    assert row["word_count"] == 120
    assert row["language"] == "fa"  # the row's own language is not wiped
    assert row["finished_at"]


def test_a_cancelled_run_stays_interrupted_for_the_resume_offer(tmp_path: Path) -> None:
    svc, app, db, rid, task = _setup(tmp_path)
    app.worker_events.put(_done(task, []))  # cancel: the worker writes no outputs
    app.worker_events.put(_exit())

    assert svc.settle_done_on_exit(wait_s=2.0) == 0

    row = _row(db, rid)
    assert row["status"] == "interrupted" and row["error"] == EXIT_REASON


@pytest.mark.parametrize("kind", ["missing", "empty"])
def test_outputs_that_are_not_really_on_disk_do_not_count(tmp_path: Path, kind: str) -> None:
    svc, app, db, rid, task = _setup(tmp_path)
    path = tmp_path / "talk.srt"
    if kind == "empty":
        path.write_text("", encoding="utf-8")
    app.worker_events.put(_done(task, [str(path)]))
    app.worker_events.put(_exit())

    assert svc.settle_done_on_exit(wait_s=2.0) == 0
    assert _row(db, rid)["status"] == "interrupted"


def test_a_done_event_that_arrives_late_is_still_picked_up(tmp_path: Path) -> None:
    svc, app, db, rid, task = _setup(tmp_path)
    srt = _write(tmp_path / "talk.srt")

    def _late() -> None:
        time.sleep(0.4)  # the reader thread drains the pipe after the process ended
        app.worker_events.put(_done(task, [srt]))
        app.worker_events.put(_exit())

    threading.Thread(target=_late, daemon=True).start()
    started = time.monotonic()

    assert svc.settle_done_on_exit(wait_s=3.0) == 1
    assert time.monotonic() - started < 2.0  # returned as soon as the worker's pipe ended
    assert _row(db, rid)["status"] == "finished"


def test_the_wait_is_bounded_when_no_event_ever_comes(tmp_path: Path) -> None:
    svc, _app, db, rid, _task = _setup(tmp_path)
    started = time.monotonic()

    assert svc.settle_done_on_exit(wait_s=0.5) == 0

    assert time.monotonic() - started < 2.0
    assert _row(db, rid)["status"] == "interrupted"


def test_an_event_for_another_task_is_ignored(tmp_path: Path) -> None:
    svc, app, db, rid, task = _setup(tmp_path)
    srt = _write(tmp_path / "talk.srt")
    event = _done(task, [srt])
    event["task_id"] = "h99999"  # an older task that used this worker slot
    app.worker_events.put(event)
    app.worker_events.put(_exit())

    assert svc.settle_done_on_exit(wait_s=2.0) == 0
    assert _row(db, rid)["status"] == "interrupted"


def test_a_row_the_user_already_cancelled_is_not_overwritten(tmp_path: Path) -> None:
    svc, app, db, rid, task = _setup(tmp_path)
    db.dismiss_interrupted_transcriptions([rid])  # now 'cancelled'
    srt = _write(tmp_path / "talk.srt")
    app.worker_events.put(_done(task, [srt]))
    app.worker_events.put(_exit())

    svc.settle_done_on_exit(wait_s=2.0)

    assert _row(db, rid)["status"] == "cancelled"


def test_nothing_happens_without_a_history_or_a_running_task(tmp_path: Path) -> None:
    svc, app, _db, _rid, task = _setup(tmp_path)
    app.history = None
    assert svc.settle_done_on_exit(wait_s=0.2) == 0
    app.history = HistoryDB(tmp_path / "other.db")
    task.status = "finished"
    assert svc.settle_done_on_exit(wait_s=0.2) == 0


def test_a_failing_history_write_is_logged_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    svc, app, db, _rid, task = _setup(tmp_path)

    def _boom(*_a: Any, **_k: Any) -> bool:
        raise OSError("disk full")

    monkeypatch.setattr(db, "mark_transcription_finished_after_exit", _boom)
    app.worker_events.put(_done(task, [_write(tmp_path / "talk.srt")]))
    app.worker_events.put(_exit())

    assert svc.settle_done_on_exit(wait_s=2.0) == 0  # teardown goes on


# ----------------------------------------------------------- the exit path wiring


def test_on_exit_settles_after_stopping_the_workers_and_before_closing_the_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: True)
    monkeypatch.setattr(app_module, "stop_live_session", lambda _a: None)
    monkeypatch.setattr(app_module, "stop_voice_clone_worker", lambda _a: None)
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_a, **_k: True)
    calls: list[str] = []
    history = types.SimpleNamespace(
        mark_transcriptions_closed_by_user=lambda ids: calls.append("record") or 1,
        close=lambda: calls.append("close"),
    )
    fake = types.SimpleNamespace(
        _exit_from_tray=True, app_config={}, tray=None,
        queue=[types.SimpleNamespace(status="running", process=None, history_id=5)],
        download_queue=[], _closing=False, _folder_watcher=None, history=history,
        withdraw=lambda: None, destroy=lambda: calls.append("destroy"),
        _save_window_geometry=lambda: None, _shutdown_server_on_exit=lambda: None,
        transcription_service=types.SimpleNamespace(
            stop_all=lambda: calls.append("stop_all"),
            settle_done_on_exit=lambda: calls.append("settle") or 0),
    )

    App.on_exit(fake)  # type: ignore[arg-type]

    assert calls == ["record", "stop_all", "settle", "close", "destroy"]


def test_a_failing_settle_does_not_stop_the_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: True)
    monkeypatch.setattr(app_module, "stop_live_session", lambda _a: None)
    monkeypatch.setattr(app_module, "stop_voice_clone_worker", lambda _a: None)
    calls: list[str] = []

    def _boom() -> int:
        raise RuntimeError("settle failed")

    fake = types.SimpleNamespace(
        _exit_from_tray=True, app_config={}, tray=None, queue=[], download_queue=[],
        _closing=False, _folder_watcher=None, history=None,
        withdraw=lambda: None, destroy=lambda: calls.append("destroy"),
        _save_window_geometry=lambda: None, _shutdown_server_on_exit=lambda: None,
        transcription_service=types.SimpleNamespace(
            stop_all=lambda: calls.append("stop_all"), settle_done_on_exit=_boom),
    )

    App.on_exit(fake)  # type: ignore[arg-type]

    assert calls == ["stop_all", "destroy"]


# ------------------------------------------------------------------ history method


def test_history_finishes_only_rows_that_are_still_open(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    open_row = db.insert_transcription("a.wav", language="en")
    closed = db.insert_transcription("b.wav")
    db.mark_transcriptions_closed_by_user([closed])
    cancelled = db.insert_transcription("c.wav")
    db.finish_transcription(cancelled, "cancelled")
    for rid in (open_row, closed, cancelled):
        db.mark_transcription_finished_after_exit(rid, ["x.srt"], 4.0, 9)

    rows = {r["id"]: r for r in db.list_transcriptions()}
    assert rows[open_row]["status"] == "finished" and rows[open_row]["language"] == "en"
    assert rows[closed]["status"] == "finished" and rows[closed]["error"] == ""
    assert rows[cancelled]["status"] == "cancelled"
    assert db.mark_transcription_finished_after_exit(0, [], 0.0, 0) is False
