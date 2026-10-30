"""A worker error after the user's Cancel that lists written files follows the
same rule as Cancel followed by ``done``: all formats written -> finished,
a partial set -> cancelled. Windowless."""
from __future__ import annotations

from tests.app.test_cancel_stays_cancelled import _Task, _rig, _user_cancels


def _cancel_then_error_with_outputs(monkeypatch, tmp_path, written):
    task = _Task(file_path=str(tmp_path / "test.mp3"), output_formats=["srt", "json"])
    app, svc, worker, rows = _rig(monkeypatch, task)
    paths = []
    for name in written:
        p = tmp_path / name
        p.write_text("x", encoding="utf-8")
        paths.append(str(p))
    _user_cancels(task)
    app.worker_events.put({
        "event": "error", "message": "late step failed", "outputs": paths,
        "_worker_id": 1, "_token": "test-token",
    })
    svc._poll_once()
    return task, rows


def test_error_after_cancel_with_complete_outputs_is_finished(monkeypatch, tmp_path):
    task, rows = _cancel_then_error_with_outputs(monkeypatch, tmp_path, ["test.srt", "test.json"])
    assert task.status == "finished"
    assert [r["status"] for r in rows] == ["finished"]


def test_error_after_cancel_with_partial_outputs_stays_cancelled(monkeypatch, tmp_path):
    task, rows = _cancel_then_error_with_outputs(monkeypatch, tmp_path, ["test.srt"])
    assert task.status == "cancelled"
    assert [r["status"] for r in rows] == ["cancelled"]
