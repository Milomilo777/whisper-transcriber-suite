"""finish_task's fallback output-path derivation (windowless).

An older worker's ``done`` event carries no ``outputs`` list, so
finish_task derives the history row's file names itself. The derivation
must describe what THIS run was dispatched to write (the task's stamped
``output_formats``, mapped to the on-disk extension), never the live
config's format keys — the config can have changed since dispatch, and a
format key is not always the extension the writer uses (``elan`` writes
``.eaf``).
"""
from __future__ import annotations

import queue
import time
from types import SimpleNamespace

from app.services.transcription_service import TranscriptionService
from core.history import HistoryDB
from core.task import TranscriptionTask


class _Calls:
    def __init__(self) -> None:
        self.shown: list = []
        self.logs: list[str] = []


def _app(tmp_path, calls: _Calls, live_formats):
    hist = HistoryDB(tmp_path / "history.db")
    app = SimpleNamespace(
        worker_events=queue.Queue(), workers=[], queue=[],
        app_config={"transcribe_backend": "faster_whisper",
                    "output_formats": list(live_formats)},
        after=lambda *a, **k: None, log=calls.logs.append,
        update_overall_progress=lambda: None, refresh=lambda: None,
        refresh_download_queue=lambda: None, model_status=lambda m: None,
        show_last_result=calls.shown.append, note_job_success=lambda: None,
        history=hist, post_to_main=lambda fn: fn(), status_var=None,
    )
    return app, hist


def _worker(wid: int, token: str, task=None):
    return {"id": wid, "process": None, "ready": True, "task": task,
            "temporary": False, "token": token, "last_event_at": 0.0,
            "stdin_lock": None}


def _task(path: str, hist: HistoryDB, formats) -> TranscriptionTask:
    t = TranscriptionTask(path)
    t.history_id = hist.insert_transcription(path)
    t.status = "running"
    t.start_time = time.time()
    t.task_id = f"h{t.history_id}"
    # What dispatch_waiting stamped for THIS run.
    t.output_formats = list(formats)
    return t


def _done_without_outputs(t):
    return {"event": "done", "task_id": t.task_id, "word_count": 0,
            "audio_duration": 0.0, "no_speech": False,
            "_token": "tok1", "_worker_id": 1, "_pid": 5}


def test_derived_paths_use_the_tasks_formats_and_mapped_extension(tmp_path):
    """The run was dispatched with "elan" (writes .eaf); the live config
    still says srt+json. The history row must name the .eaf this run
    wrote, not .srt/.json names derived from the current config."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls, live_formats=["srt", "json"])
    svc = TranscriptionService(app)
    out = tmp_path / "p.eaf"
    out.write_text("<ANNOTATION_DOCUMENT/>", encoding="utf-8")
    t = _task(str(tmp_path / "p.mp4"), hist, formats=["elan"])
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put(_done_without_outputs(t))
    svc.poll()
    row = hist.list_transcriptions()[0]
    assert row["status"] == "finished"
    assert row["output_paths"] == [str(out)]


def test_derived_paths_follow_a_mid_run_config_change(tmp_path):
    """The run was dispatched with docx only; the user then switched the
    selection back to srt+json while it ran. The row records the docx
    this run wrote, not the srt/json the config now lists."""
    calls = _Calls()
    app, hist = _app(tmp_path, calls, live_formats=["srt", "json"])
    svc = TranscriptionService(app)
    out = tmp_path / "p.docx"
    out.write_bytes(b"PK\x03\x04not-a-real-docx")
    t = _task(str(tmp_path / "p.mp4"), hist, formats=["docx"])
    app.workers.append(_worker(1, "tok1", t))
    app.worker_events.put(_done_without_outputs(t))
    svc.poll()
    row = hist.list_transcriptions()[0]
    assert row["output_paths"] == [str(out)]
