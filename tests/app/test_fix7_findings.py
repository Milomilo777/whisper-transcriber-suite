"""Fix-7 regression tests (F1/F2/F4/F5/F6).

Style follows the existing suite in this directory: SimpleNamespace-based
fakes, no real Tk/subprocess/model. Each test fails pre-fix and passes
post-fix in the real repo (where ``app.services.transcription_service``
and ``core.*`` resolve).
"""
from __future__ import annotations

import queue
import threading
import time
import types
from types import SimpleNamespace

from app.services.transcription_service import (
    TranscriptionService,
    task_correlation_id,
)


class _AliveProc:
    def __init__(self, pid=100):
        self.pid = pid
        self.stdin = SimpleNamespace(
            write=lambda s: None, flush=lambda: None
        )

    def poll(self):
        return None


def _poll_app(workers, q=None):
    q = q or queue.Queue()
    app = SimpleNamespace(
        worker_events=q,
        workers=workers,
        app_config={},
        after=lambda *a, **k: None,
        log=lambda m: None,
        update_overall_progress=lambda: None,
        refresh=lambda: None,
        refresh_download_queue=lambda: None,
        model_status=lambda m: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    return svc, app, q


def _task(task_id="", history_id=0, status="running", **kw):
    base = dict(
        task_id=task_id,
        history_id=history_id,
        status=status,
        cancelled=False,
        progress=0,
        start_time=time.time(),
        end_time=None,
        file_path="clip.mp4",
        output_paths=[],
        source_download=None,
        detected_language="",
        language_probability=0.0,
        word_count=0,
        audio_duration=0.0,
    )
    base.update(kw)
    return SimpleNamespace(**base)


# ---------------------------------------------------------------- F1

def test_f1_stale_progress_is_dropped_not_misapplied():
    new_task = _task(task_id="h2", history_id=2, status="running")
    new_task.progress = 0
    proc = _AliveProc(pid=111)
    worker = {
        "id": 1, "process": proc, "task": new_task, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    svc, app, q = _poll_app([worker])
    q.put({
        "event": "progress", "percent": 99, "task_id": "h1",
        "_worker_id": 1, "_pid": 111,
    })
    svc.poll()
    assert new_task.progress == 0


def test_f1_matching_progress_still_applies():
    task = _task(task_id="h2", history_id=2, status="running")
    proc = _AliveProc(pid=111)
    worker = {
        "id": 1, "process": proc, "task": task, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    svc, app, q = _poll_app([worker])
    q.put({
        "event": "progress", "percent": 42, "task_id": "h2",
        "_worker_id": 1, "_pid": 111,
    })
    svc.poll()
    assert task.progress == 42


def test_f1_idless_progress_still_applies_for_old_workers():
    task = _task(task_id="h2", history_id=2, status="running")
    proc = _AliveProc(pid=111)
    worker = {
        "id": 1, "process": proc, "task": task, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    svc, app, q = _poll_app([worker])
    q.put({"event": "progress", "percent": 7, "_worker_id": 1, "_pid": 111})
    svc.poll()
    assert task.progress == 7


def test_f1_stale_done_does_not_finish_the_new_task(monkeypatch):
    new_task = _task(task_id="h2", history_id=2, status="running")
    proc = _AliveProc(pid=111)
    worker = {
        "id": 1, "process": proc, "task": new_task, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    svc, app, q = _poll_app([worker])
    finished = []
    monkeypatch.setattr(
        svc, "finish_task", lambda w, keep_status=False: finished.append(w)
    )
    q.put({
        "event": "done", "task_id": "h1", "outputs": [],
        "_worker_id": 1, "_pid": 111,
    })
    svc.poll()
    assert finished == []
    assert worker["task"] is new_task
    assert new_task.status == "running"


def test_f1_stale_error_does_not_fail_the_new_task(monkeypatch):
    new_task = _task(task_id="h2", history_id=2, status="running")
    proc = _AliveProc(pid=111)
    worker = {
        "id": 1, "process": proc, "task": new_task, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    svc, app, q = _poll_app([worker])
    finished = []
    monkeypatch.setattr(
        svc, "finish_task", lambda w, keep_status=False: finished.append(w)
    )
    q.put({
        "event": "error", "message": "old task boom", "task_id": "h1",
        "_worker_id": 1, "_pid": 111,
    })
    svc.poll()
    assert finished == []
    assert new_task.status == "running"


def test_f1_dispatch_failure_event_carries_task_id():
    task = _task(task_id="", history_id=8, status="waiting")
    # Prime the cache so the expected id is deterministic.
    assert task_correlation_id(task) == "h8"
    proc = _AliveProc(pid=222)
    worker = {
        "id": 3, "process": proc, "task": task, "ready": True,
        "stdin_lock": threading.Lock(),
    }
    q: "queue.Queue[dict]" = queue.Queue()
    app = SimpleNamespace(worker_events=q)
    svc = TranscriptionService(app)  # type: ignore[arg-type]

    def _boom(worker, msg):
        raise OSError("pipe broken")

    svc._locked_stdin_write = _boom  # type: ignore[method-assign]
    svc._dispatch_command_async(worker, task, {"action": "transcribe"})
    deadline = time.time() + 3.0
    event = None
    while time.time() < deadline:
        try:
            event = q.get_nowait()
            break
        except Exception:
            time.sleep(0.01)
    assert event is not None
    assert event["event"] == "error"
    assert event.get("task_id") == "h8"


# ---------------------------------------------------------------- F2

def test_f2_retry_gets_a_fresh_correlation_id(monkeypatch):
    task = _task(task_id="h5", history_id=5, status="waiting")
    proc = _AliveProc(pid=333)
    worker = {
        "id": 1, "process": proc, "task": None, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    app = SimpleNamespace(
        queue=[task],
        workers=[worker],
        parallel_workers=1,
        app_config={"model": {"name": "m"}, "output_formats": ["srt"]},
        history=SimpleNamespace(
            insert_transcription=lambda **k: 99,
        ),
        update_overall_progress=lambda: None,
        log=lambda m: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    captured = {}
    monkeypatch.setattr(
        svc, "_dispatch_command_async",
        lambda w, t, cmd: captured.setdefault("cmd", cmd),
    )
    # idle_workers()/active_workers() need process.poll() is None + ready.
    svc.dispatch_waiting()
    assert task.history_id == 99
    assert captured["cmd"]["task_id"] == "h99"
    assert task_correlation_id(task) == "h99"
    # Same-attempt consistency: a later control agrees with the dispatch.
    assert task.task_id == "h99"


def test_f2_first_dispatch_caches_from_fresh_history_id(monkeypatch):
    task = _task(task_id="", history_id=0, status="waiting")
    proc = _AliveProc(pid=334)
    worker = {
        "id": 1, "process": proc, "task": None, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    app = SimpleNamespace(
        queue=[task],
        workers=[worker],
        parallel_workers=1,
        app_config={"model": {"name": "m"}, "output_formats": ["srt"]},
        history=SimpleNamespace(
            insert_transcription=lambda **k: 7,
        ),
        update_overall_progress=lambda: None,
        log=lambda m: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    captured = {}
    monkeypatch.setattr(
        svc, "_dispatch_command_async",
        lambda w, t, cmd: captured.setdefault("cmd", cmd),
    )
    svc.dispatch_waiting()
    assert captured["cmd"]["task_id"] == "h7"


# ---------------------------------------------------------------- F4

def test_f4_startup_error_finishes_orphaned_tasks(monkeypatch):
    import app.services.transcription_service as ts_mod

    failed_proc = _AliveProc(pid=501)
    healthy_proc = _AliveProc(pid=502)
    failed_worker = {
        "id": 1, "process": failed_proc, "task": None, "ready": False,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    orphan = _task(task_id="h20", history_id=20, status="running")
    healthy_worker = {
        "id": 2, "process": healthy_proc, "task": orphan, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    q: "queue.Queue[dict]" = queue.Queue()
    finished_rows = []
    history = SimpleNamespace(
        finish_transcription=lambda *a, **k: (
            finished_rows.append(k), True
        )[1]
    )
    app = SimpleNamespace(
        worker_events=q,
        workers=[failed_worker, healthy_worker],
        app_config={},
        model_setup_running=False,  # enter the faster_whisper teardown branch
        after=lambda *a, **k: None,
        log=lambda m: None,
        update_overall_progress=lambda: None,
        show_last_result=lambda t: None,
        refresh_download_queue=lambda: None,
        history=history,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "stop_all", lambda: None)
    monkeypatch.setattr(
        svc, "_derive_transcript_stats", lambda task: (0, 0.0)
    )
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: None)

    # poll() does "from core.backends import availability as _eng" inline;
    # stub the import so the test is hermetic and deterministic.
    import sys

    fake_availability = SimpleNamespace(
        normalise_engine=lambda v: "faster_whisper",
        VALUE_TO_LABEL={},
    )
    core_pkg = sys.modules.get("core")
    if core_pkg is None:
        core_pkg = types.ModuleType("core")
        monkeypatch.setitem(sys.modules, "core", core_pkg)
    backends_pkg = types.ModuleType("core.backends")
    backends_pkg.availability = fake_availability  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.backends", backends_pkg)
    monkeypatch.setitem(
        sys.modules, "core.backends.availability", fake_availability
    )

    q.put({
        "event": "startup_error", "message": "boom",
        "_worker_id": 1, "_pid": 501,
    })
    svc.poll()
    assert orphan.status == "error"
    assert healthy_worker["task"] is None
    assert finished_rows and finished_rows[0]["status"] == "error"
    assert app.workers == []


# ---------------------------------------------------------------- F5

def test_f5_worker_exit_finishes_a_cancelled_task():
    task = _task(
        task_id="h30", history_id=30, status="cancelled", cancelled=True
    )
    proc = _AliveProc(pid=601)
    worker = {
        "id": 1, "process": proc, "task": task, "ready": True,
        "last_event_at": time.time(), "token": "", "temporary": False,
    }
    q: "queue.Queue[dict]" = queue.Queue()
    app = SimpleNamespace(
        worker_events=q,
        workers=[worker],
        app_config={},
        after=lambda *a, **k: None,
        log=lambda m: None,
        update_overall_progress=lambda: None,
        show_last_result=lambda t: None,
        history=None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    svc._post_usage_stats = lambda *a, **k: None  # type: ignore[method-assign]
    q.put({"event": "worker_exit", "return_code": 1,
           "_worker_id": 1, "_pid": 601})
    svc.poll()
    assert worker["task"] is None
    assert task.status == "cancelled"


def test_f5_restart_worker_finishes_a_live_task(monkeypatch):
    task = _task(task_id="h31", history_id=31, status="running")
    worker = {
        "id": 1, "process": _AliveProc(pid=602), "task": task,
        "ready": True, "temporary": False,
    }
    app = SimpleNamespace(
        workers=[worker],
        queue=[],
        app_config={},
        after=lambda *a, **k: None,
        log=lambda m: None,
        update_overall_progress=lambda: None,
        show_last_result=lambda t: None,
        history=None,
        model_loading=False,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "stop_worker", lambda w: None)
    svc._post_usage_stats = lambda *a, **k: None  # type: ignore[method-assign]
    svc.restart_worker(worker)
    assert task.status == "error"
    assert worker["task"] is None


def test_f5_retire_worker_finishes_a_live_task(monkeypatch):
    task = _task(task_id="h32", history_id=32, status="running")
    worker = {
        "id": 1, "process": _AliveProc(pid=603), "task": task,
        "ready": True, "temporary": False,
    }
    app = SimpleNamespace(
        workers=[worker],
        queue=[],
        app_config={},
        after=lambda *a, **k: None,
        log=lambda m: None,
        update_overall_progress=lambda: None,
        show_last_result=lambda t: None,
        history=None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "stop_worker", lambda w: None)
    monkeypatch.setattr(svc, "update_model_state", lambda: None)
    svc._post_usage_stats = lambda *a, **k: None  # type: ignore[method-assign]
    svc.retire_worker(worker)
    assert task.status == "error"
    assert worker not in app.workers


# ---------------------------------------------------------------- F6

def test_f6_headless_wait_pumps_main_loop_instead_of_deadlocking(monkeypatch):
    import app.services.transcription_service as ts_mod

    monkeypatch.setattr(ts_mod, "HEADLESS_READY_TIMEOUT_S", 3.0)
    app = SimpleNamespace(
        workers=[],
        next_worker_id=1,
        app_config={},
        after=lambda *a, **k: None,
        log=lambda m: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    svc.ready_workers = lambda: []  # type: ignore[method-assign]

    def _fake_start_worker(temporary=False):
        app.workers.append({
            "id": app.next_worker_id, "process": _AliveProc(pid=701),
            "task": None, "ready": False, "temporary": temporary,
        })
        app.next_worker_id += 1

    svc.start_worker = _fake_start_worker  # type: ignore[method-assign]
    svc.retire_worker = lambda w: app.workers.remove(w)  # type: ignore[method-assign]

    pumps = []

    def _update():
        pumps.append(1)
        # Simulate poll() observing the ready event: release the waiter.
        if len(pumps) >= 2 and svc._pending_load_event is not None:
            svc._pending_load_event.set()

    app.update = _update  # type: ignore[attr-defined]
    started = time.monotonic()
    ok = svc.ensure_worker_ready(parent_widget=None, headless=True)
    elapsed = time.monotonic() - started
    assert ok is True
    assert len(pumps) >= 2
    assert elapsed < 3.0
