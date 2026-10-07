"""Worker lifecycle holes found in the second external review (card C2.51b).

W1: several ensure_worker_ready() callers wait on one loading worker.
W3: retiring a temporary worker must not block the Tk thread.
W4: a worker whose process died without a worker_exit event gets a deadline.
W5: a failed spawn or an idle death leaves no dead worker dict behind.
"""
from __future__ import annotations

import os
import threading
import time
from queue import Queue
from types import SimpleNamespace
from typing import Any

import pytest

import app.services.transcription_service as ts


class _Alive:
    pid = 4242

    def __init__(self) -> None:
        self.dead = False

    def poll(self):
        return 0 if self.dead else None

    def wait(self, timeout=None):
        if not self.dead:
            time.sleep(min(timeout or 0.01, 0.01))
        return 0


def _app(**extra: Any) -> SimpleNamespace:
    app = SimpleNamespace(
        workers=[], worker_events=Queue(), queue=[], next_worker_id=1, model_loading=False,
        status_var=SimpleNamespace(set=lambda v: None),
        entry_file=os.path.abspath("gui.py"), app_config={},
        update_overall_progress=lambda: None, log=lambda m: None, post_to_main=lambda f: None,
        refresh=lambda: None, refresh_download_queue=lambda: None, after=lambda ms, fn: None,
        worker_ready=False, model_ready=False, parallel_workers=2, _closing=False,
    )
    for k, v in extra.items():
        setattr(app, k, v)
    return app


def _svc(app: SimpleNamespace) -> ts.TranscriptionService:
    svc = ts.TranscriptionService(app)  # type: ignore[arg-type]

    def fake_start(worker=None, temporary=False):
        w = {"id": app.next_worker_id, "process": _Alive(), "ready": False, "task": None,
             "temporary": temporary, "token": f"tok{app.next_worker_id}",
             "last_event_at": time.time(), "stdin_lock": threading.Lock(), "device": "",
             "compute_type": "", "requested_device": "", "downgraded": False}
        app.next_worker_id += 1
        app.workers.append(w)

    svc.start_worker = fake_start  # type: ignore[method-assign]
    svc._refresh_device_badge = lambda: None  # type: ignore[method-assign]
    return svc


# --- W1 ----------------------------------------------------------------------


def test_two_headless_waiters_both_see_the_worker_ready(monkeypatch):
    """Reproduces the verifier's probe p3_f: caller B re-enters through the
    headless pump while caller A waits. Before the fix B overwrote A's single
    waiter slot, A burned the whole timeout and then retired the worker B
    was using."""
    monkeypatch.setattr(ts, "HEADLESS_READY_TIMEOUT_S", 3.0)
    app = _app()
    svc = _svc(app)
    state: dict[str, Any] = {"n": 0}

    def update():
        state["n"] += 1
        if state["n"] == 1:
            state["B"] = svc.ensure_worker_ready(None, headless=True)  # type: ignore[arg-type]
        if state["n"] == 4 and not app.workers[0]["ready"]:
            app.worker_events.put({"event": "ready", "_token": "tok1", "_worker_id": 1, "_pid": 4242})
            svc.poll()

    app.update = update
    t0 = time.monotonic()
    a = svc.ensure_worker_ready(None, headless=True)  # type: ignore[arg-type]
    elapsed = time.monotonic() - t0
    assert state["B"] is True
    assert a is True
    assert elapsed < 2.0, f"caller A waited {elapsed:.1f}s for a worker that was ready"
    assert [w["id"] for w in app.workers] == [1]
    assert app.workers[0]["ready"] is True
    assert svc._load_waiters == []


def test_release_wakes_every_waiter_of_that_worker():
    app = _app()
    svc = _svc(app)
    first, second, other = threading.Event(), threading.Event(), threading.Event()
    svc._add_load_waiter(3, first, None)
    svc._add_load_waiter(3, second, None)
    svc._add_load_waiter(4, other, None)
    svc._release_pending_load({"id": 3}, success=True)
    assert first.is_set() and second.is_set()
    assert not other.is_set()
    assert [w["worker_id"] for w in svc._load_waiters] == [4]


def test_timeout_does_not_retire_a_worker_another_caller_waits_for(monkeypatch):
    monkeypatch.setattr(ts, "HEADLESS_READY_TIMEOUT_S", 0.3)
    app = _app()
    svc = _svc(app)
    state: dict[str, Any] = {"n": 0}

    def update():
        state["n"] += 1
        if state["n"] == 1:
            # B adopts A's loading worker and is still waiting when A times out.
            svc._add_load_waiter(1, threading.Event(), None)

    app.update = update
    assert svc.ensure_worker_ready(None, headless=True) is False  # type: ignore[arg-type]
    assert [w["id"] for w in app.workers] == [1], "the worker B waits for was retired"


def test_headless_wait_stops_when_the_window_closes(monkeypatch):
    """W2: after the window starts closing poll() no longer runs, so no ready
    event can arrive; the wait ends instead of burning the timeout."""
    monkeypatch.setattr(ts, "HEADLESS_READY_TIMEOUT_S", 30.0)
    app = _app()
    svc = _svc(app)

    def update():
        app._closing = True

    app.update = update
    t0 = time.monotonic()
    assert svc.ensure_worker_ready(None, headless=True) is False  # type: ignore[arg-type]
    assert time.monotonic() - t0 < 2.0


# --- W3 ----------------------------------------------------------------------


class _SlowExit:
    """A worker process that takes ``delay`` seconds to exit after shutdown."""

    pid = 777
    stdin = None

    def __init__(self, delay: float) -> None:
        self.delay = delay
        self.started = None
        self.killed = False

    def poll(self):
        if self.killed:
            return 0
        return None

    def wait(self, timeout=None):
        if self.started is None:
            self.started = time.monotonic()
        left = self.delay - (time.monotonic() - self.started)
        if timeout is not None and left > timeout:
            time.sleep(timeout)
            raise ts.subprocess.TimeoutExpired("worker", timeout)
        time.sleep(max(0.0, left))
        self.killed = True
        return 0


def test_retire_worker_does_not_block_the_caller():
    app = _app()
    svc = _svc(app)
    proc = _SlowExit(1.5)
    worker = {"id": 9, "process": proc, "ready": True, "task": None, "temporary": True,
              "stdin_lock": threading.Lock()}
    app.workers.append(worker)
    t0 = time.monotonic()
    svc.retire_worker(worker)
    assert time.monotonic() - t0 < 0.5
    assert worker not in app.workers
    assert worker["process"] is None
    # The helper thread still finishes the stop; stop_all covers it meanwhile.
    assert [w["process"] for w in svc._retiring] == [proc]
    deadline = time.monotonic() + 5
    while svc._retiring and time.monotonic() < deadline:
        time.sleep(0.05)
    assert svc._retiring == []
    assert proc.killed


def test_stop_all_also_stops_a_worker_still_being_retired(monkeypatch):
    app = _app()
    svc = _svc(app)
    stopped: list[list[Any]] = []
    shadow = {"id": 3, "process": _Alive(), "stdin_lock": threading.Lock()}
    svc._retiring.append(shadow)
    monkeypatch.setattr(svc, "_stop_workers", lambda ws: stopped.append(list(ws)))
    svc.stop_all()
    assert stopped == [[shadow]]


# --- W4 ----------------------------------------------------------------------


class _Task:
    def __init__(self) -> None:
        self.status = "running"


def test_dead_worker_without_worker_exit_gets_a_deadline(monkeypatch):
    """The verifier's probe: a dead process whose stdout a grandchild keeps
    open never queues worker_exit; its task stayed 'running' forever."""
    app = _app()
    svc = _svc(app)
    finished: list[Any] = []
    monkeypatch.setattr(svc, "finish_task", lambda w, keep_status=False: (
        finished.append(w["task"]), w.__setitem__("task", None)))
    proc = _Alive()
    proc.dead = True
    task = _Task()
    worker = {"id": 1, "process": proc, "ready": True, "task": task, "temporary": False,
              "token": "tokX", "last_event_at": time.time(), "stdin_lock": threading.Lock()}
    app.workers.append(worker)
    svc.poll()
    assert task.status == "running"  # inside the grace period
    worker["dead_since"] -= svc.DEAD_WORKER_GRACE_S + 1
    svc.poll()  # synthesizes worker_exit
    svc.poll()  # handles it
    assert task.status == "error"
    assert finished == [task]
    assert worker["process"] is None


# --- W5 ----------------------------------------------------------------------


def test_failed_spawn_leaves_no_worker_dict(monkeypatch):
    app = _app()
    svc = ts.TranscriptionService(app)  # type: ignore[arg-type]

    def _refuse(*_a, **_k):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(ts.subprocess, "Popen", _refuse)
    with pytest.raises(PermissionError):
        svc.start_worker(temporary=True)
    assert app.workers == []


def test_idle_worker_exit_drops_the_dict():
    app = _app()
    svc = _svc(app)
    proc = _Alive()
    worker = {"id": 1, "process": proc, "ready": True, "task": None, "temporary": False,
              "token": "tok1", "last_event_at": time.time(), "stdin_lock": threading.Lock()}
    app.workers.append(worker)
    proc.dead = True
    app.worker_events.put({"event": "worker_exit", "return_code": 1, "_pid": proc.pid,
                           "_worker_id": 1, "_token": "tok1"})
    svc.poll()
    assert app.workers == []


def test_exit_of_a_worker_being_restarted_keeps_the_dict():
    """restart_worker drops the process handle before the old process's
    worker_exit arrives; that dict is about to get a new process."""
    app = _app()
    svc = _svc(app)
    worker = {"id": 1, "process": None, "ready": False, "task": None, "temporary": False,
              "token": "tok1", "last_event_at": time.time(), "stdin_lock": threading.Lock()}
    app.workers.append(worker)
    app.worker_events.put({"event": "worker_exit", "return_code": 0, "_pid": 4242,
                           "_worker_id": 1, "_token": "tok1"})
    svc.poll()
    assert app.workers == [worker]


# --- W6 ----------------------------------------------------------------------


def test_voice_worker_survives_an_unwritable_log_folder(monkeypatch):
    import io
    import sys
    import types

    from core import offline, optional_deps
    from core import voice_clone_worker as vcw

    def _no_log_dir(*_a, **_k):
        raise FileExistsError(183, "Cannot create a file when that file already exists")

    emitted: list[str] = []
    monkeypatch.setattr(vcw, "setup_logging", _no_log_dir)
    monkeypatch.setattr(offline, "install_network_guard", lambda: None)
    monkeypatch.setattr(optional_deps, "activate", lambda: None)
    monkeypatch.setattr(vcw, "_exit_if_orphaned", lambda *a, **k: None)
    monkeypatch.setattr(vcw, "emit", lambda event, **_k: emitted.append(event))
    monkeypatch.setitem(sys.modules, "core.voice_clone", types.ModuleType("core.voice_clone"))
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"action": "shutdown"}\n'))
    assert vcw.main() == 0
    assert "ready" in emitted


# --- W7 ----------------------------------------------------------------------


def test_voice_reader_survives_a_deeply_nested_line():
    from app.services.voice_clone_service import VoiceCloneWorker

    vw = VoiceCloneWorker("x")  # type: ignore[arg-type]
    deep = "[" * 200000 + "]" * 200000
    logged: list[str] = []
    vw._log_line = logged.append  # type: ignore[method-assign]
    vw._process = SimpleNamespace(  # type: ignore[assignment]
        stdout=iter([deep + "\n", '{"event": "heartbeat"}\n']), poll=lambda: None)
    vw._read_loop()
    assert logged and logged[0].startswith("[[[")


# --- W9 ----------------------------------------------------------------------


@pytest.mark.parametrize("name", [
    "clip.ts", "clip.m2ts", "clip.MTS", "clip.vob", "clip.wmv", "clip.wma",
    "clip.avi", "clip.m4v", "clip.3gp", "clip.flv", "clip.mpg",
])
def test_more_media_types_are_picked_up(tmp_path, name):
    from core.watcher import is_media_file

    path = tmp_path / name
    path.write_bytes(b"\x47" + b"\x00" * 187)
    assert is_media_file(str(path))


def test_typescript_source_is_not_media(tmp_path):
    from core.watcher import is_media_file

    source = tmp_path / "index.ts"
    source.write_text("export const x = 1;\n", encoding="utf-8")
    assert not is_media_file(str(source))
    # Still empty (being copied) or unreadable: given the benefit of the doubt.
    empty = tmp_path / "rec.ts"
    empty.write_bytes(b"")
    assert is_media_file(str(empty))
    assert not is_media_file(str(tmp_path / "notes.txt"))


def test_folder_drop_takes_the_new_types(tmp_path):
    from app.app import _media_files_in_folder

    (tmp_path / "a.wmv").write_bytes(b"x")
    (tmp_path / "b.ts").write_bytes(b"\x47\x00")
    (tmp_path / "c.ts").write_text("let y = 2;\n", encoding="utf-8")
    (tmp_path / "d.txt").write_text("no", encoding="utf-8")
    names = [os.path.basename(p) for p in _media_files_in_folder(str(tmp_path))]
    assert names == ["a.wmv", "b.ts"]
