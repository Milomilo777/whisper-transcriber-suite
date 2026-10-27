"""One model worker at a time; resumed history rows are not offered again.

* ``ensure_worker_ready`` waits for a worker that is still loading instead of
  spawning a second one beside it.
* Cancel -> Generate in the voice tab waits for the cancelled voice worker
  to be gone before a new one starts.
* YES to "Resume interrupted transcriptions?" retires the offered rows.
"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from queue import Queue
from types import SimpleNamespace
from typing import Any

import pytest

import app.services.transcription_service as ts_mod
from app.services.transcription_service import TranscriptionService


# ------------------------------------------------- transcription worker


class _LiveProc:
    pid = 1
    stdin = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def _service():
    app = SimpleNamespace(workers=[], next_worker_id=1, worker_events=Queue(),
                          status_var=None, after=lambda *a: None, update=lambda: None,
                          post_to_main=lambda fn: fn())
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    spawned: list[int] = []

    def fake_start(worker=None, temporary=False):
        w = {"id": app.next_worker_id, "process": _LiveProc(), "ready": False, "task": None}
        app.next_worker_id += 1
        app.workers.append(w)
        spawned.append(w["id"])

    svc.start_worker = fake_start  # type: ignore[method-assign]
    return svc, app, spawned


def _wait_ready_in_thread(svc):
    result: dict[str, Any] = {}
    th = threading.Thread(
        target=lambda: result.setdefault("ok", svc.ensure_worker_ready(svc.app, headless=True)))
    th.start()
    return th, result


def test_a_loading_worker_is_awaited_not_doubled():
    svc, app, spawned = _service()
    svc.start_worker()  # the watched folder / crash resume started worker 1
    th, result = _wait_ready_in_thread(svc)
    deadline = time.monotonic() + 5
    while svc._pending_load_worker_id is None and time.monotonic() < deadline:
        time.sleep(0.01)
    assert svc._pending_load_worker_id == 1
    app.workers[0]["ready"] = True
    svc._release_pending_load(app.workers[0], success=True)
    th.join(5)
    assert result.get("ok") is True
    assert spawned == [1]


def test_an_adopted_worker_is_not_retired_on_timeout(monkeypatch):
    svc, app, spawned = _service()
    svc.start_worker()
    retired: list[int] = []
    monkeypatch.setattr(svc, "retire_worker", lambda w: retired.append(w["id"]))
    monkeypatch.setattr(ts_mod, "HEADLESS_READY_TIMEOUT_S", 0.2)
    th, result = _wait_ready_in_thread(svc)
    th.join(5)
    assert result.get("ok") is False
    assert spawned == [1] and retired == []  # its starter still waits for it


def test_a_worker_spawned_here_is_still_retired_on_timeout(monkeypatch):
    svc, app, spawned = _service()
    retired: list[int] = []
    monkeypatch.setattr(svc, "retire_worker", lambda w: retired.append(w["id"]))
    monkeypatch.setattr(ts_mod, "HEADLESS_READY_TIMEOUT_S", 0.2)
    th, result = _wait_ready_in_thread(svc)
    th.join(5)
    assert result.get("ok") is False
    assert spawned == [1] and retired == [1]


# ------------------------------------------------- voice-clone worker

_STUB = (
    "import json, sys, time\n"
    "print(json.dumps({'event': 'ready'}), flush=True)\n"
    "for raw in sys.stdin:\n"
    "    cmd = json.loads(raw)\n"
    "    if cmd.get('action') == 'shutdown':\n"
    "        break\n"
    "    print(json.dumps({'event': 'started', 'id': cmd['id']}), flush=True)\n"
    "    time.sleep(30)  # a blocking model.generate(): reads no stdin meanwhile\n"
)


def test_cancelled_voice_worker_is_waited_for_before_a_new_one(tmp_path: Path, monkeypatch):
    import subprocess

    from app.services import voice_clone_service as vcs

    stub = tmp_path / "stub_worker.py"
    stub.write_text(_STUB, encoding="utf-8")

    class Stub(vcs.VoiceCloneWorker):
        STOP_GRACE_S = 2.0

        def start(self) -> None:
            self._process = subprocess.Popen(
                [sys.executable, "-u", str(stub)], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

    w = Stub("entry.py")
    w.start()
    old = w._process
    assert old is not None
    try:
        errors: list[str] = []

        def gen() -> None:
            try:
                w.generate("hi", [], "o.wav", consent_accepted=False)
            except vcs.VoiceCloneWorkerError as e:
                errors.append(str(e))

        g = threading.Thread(target=gen)
        g.start()
        time.sleep(0.5)
        stopper = threading.Thread(target=w.stop)  # the tab's Cancel
        stopper.start()
        g.join(5)
        assert errors  # generate() gave up at once; the tab enables Generate
        assert not w.is_running() and old.poll() is None  # ... while it still lives
        assert w.wait_for_exit(timeout=10)
        assert old.poll() is not None
        stopper.join(10)
    finally:
        if old.poll() is None:
            old.kill()


def test_tab_waits_for_the_old_worker_before_starting_a_new_one(monkeypatch):
    from app.services import voice_clone_service as vcs
    from app.widgets import voice_clone_tab as vct

    calls: list[str] = []

    class Old:
        def __init__(self, gone: bool) -> None:
            self.gone = gone

        def is_running(self) -> bool:
            return False

        def wait_for_exit(self, timeout: float = 15.0) -> bool:
            calls.append("wait")
            return self.gone

    class New:
        def __init__(self, entry_file, log=None) -> None:
            calls.append("new")

        def start(self) -> None:
            calls.append("start")

    monkeypatch.setattr(vcs, "VoiceCloneWorker", New)
    app = SimpleNamespace(vc_worker=Old(gone=True), entry_file="entry.py",
                          log_threadsafe=lambda m: None)
    vct._ensure_worker(app)
    assert calls == ["wait", "new", "start"]

    calls.clear()
    stuck = Old(gone=False)
    app.vc_worker = stuck
    with pytest.raises(vcs.VoiceCloneWorkerError):
        vct._ensure_worker(app)
    assert calls == ["wait"] and app.vc_worker is stuck


# ------------------------------------------------- crash resume


def _interrupted_history(tmp_path: Path):
    from core.history import HistoryDB

    media = tmp_path / "talk.mp4"
    media.write_bytes(b"x")
    db = HistoryDB(tmp_path / "history.db")
    ids = [db.insert_transcription(str(media)) for _ in range(2)]  # same file twice
    db.mark_interrupted()
    return db, ids


def _offered(db) -> list[int]:
    return [r["id"] for r in db.list_transcriptions(200) if r["status"] == "interrupted"]


@pytest.mark.parametrize("answer", [True, False])
def test_answered_resume_prompt_is_not_offered_again(tmp_path: Path, monkeypatch, answer):
    from app import app as app_module
    from app.app import App

    db, ids = _interrupted_history(tmp_path)
    try:
        monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: answer)
        ns = SimpleNamespace(history=db, queue=[], refresh=lambda: None, log=lambda m: None,
                             _when_worker_ready=lambda on_ready, **k: on_ready())
        App._maybe_offer_crash_resume(ns)  # type: ignore[arg-type]
        assert len(ns.queue) == (1 if answer else 0)
        assert _offered(db) == []  # the next launch has nothing to offer
        statuses = {r["id"]: r["status"] for r in db.list_transcriptions(200)}
        assert [statuses[i] for i in ids] == ["cancelled", "cancelled"]
    finally:
        db.close()


def test_resumed_job_keeps_its_time_range_and_languages(tmp_path: Path, monkeypatch):
    from app import app as app_module
    from app.app import App
    from core.history import HistoryDB

    media = tmp_path / "talk.mp4"
    media.write_bytes(b"x")
    db = HistoryDB(tmp_path / "history.db")
    try:
        db.insert_transcription(str(media), language="fa", run_options={
            "clip_start": 60.0, "clip_end": 120.0, "languages": ["fa", "en"]})
        db.mark_interrupted()
        monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: True)
        ns = SimpleNamespace(history=db, queue=[], refresh=lambda: None, log=lambda m: None,
                             _when_worker_ready=lambda on_ready, **k: on_ready())
        App._maybe_offer_crash_resume(ns)  # type: ignore[arg-type]
        (task,) = ns.queue
        assert (task.clip_start, task.clip_end, task.languages) == (60.0, 120.0, ("fa", "en"))
        assert task.language == "fa"
    finally:
        db.close()


def test_rows_stay_offered_when_the_model_never_loads(tmp_path: Path, monkeypatch):
    from app import app as app_module
    from app.app import App

    db, ids = _interrupted_history(tmp_path)
    try:
        monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: True)
        ns = SimpleNamespace(history=db, queue=[], refresh=lambda: None, log=lambda m: None,
                             _when_worker_ready=lambda on_ready, on_timeout, **k: on_timeout())
        App._maybe_offer_crash_resume(ns)  # type: ignore[arg-type]
        assert ns.queue == [] and sorted(_offered(db)) == sorted(ids)
    finally:
        db.close()


def test_a_second_instance_does_not_offer_crash_resume(tmp_path: Path, monkeypatch):
    from app import app as app_module
    from app.app import App

    db, ids = _interrupted_history(tmp_path)
    try:
        monkeypatch.setattr(app_module.messagebox, "askyesno",
                            lambda *a, **k: pytest.fail("must not ask"))
        ns = SimpleNamespace(history=db, queue=[], _history_owner=False)
        App._maybe_offer_crash_resume(ns)  # type: ignore[arg-type]
        assert ns.queue == [] and sorted(_offered(db)) == sorted(ids)
    finally:
        db.close()


def _ns_for_resume(db):
    return SimpleNamespace(history=db, queue=[], refresh=lambda: None, log=lambda m: None,
                           _when_worker_ready=lambda on_ready, **k: on_ready())


def test_declining_resume_keeps_the_partial_text_aside(tmp_path: Path, monkeypatch):
    """Answering No must not delete what was already transcribed."""
    from app import app as app_module
    from app.app import App
    from core import _checkpoint as cp

    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path / "data")
    db, ids = _interrupted_history(tmp_path)
    media = str(tmp_path / "talk.mp4")
    try:
        cp.write_checkpoint(
            media, backend="faster-whisper", model_name="small", language="en",
            language_probability=1.0, cfg_fingerprint="f", last_end_time=5.0,
            segments=[{"start": 0.0, "end": 5.0, "text": "precious words"}],
            checkpoint_time=1.0)
        monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: False)
        logged: list[str] = []
        ns = _ns_for_resume(db)
        ns.log = logged.append
        App._maybe_offer_crash_resume(ns)  # type: ignore[arg-type]
        assert not cp.has_checkpoint(media)  # no longer offered for resume
        kept = list(cp.partials_dir().glob("*.json.unverified-*"))
        assert len(kept) == 1
        texts = list(cp.partials_dir().glob("*.txt"))
        assert len(texts) == 1 and "precious words" in texts[0].read_text(encoding="utf-8")
        assert any(str(kept[0]) in m for m in logged)
    finally:
        db.close()


def test_interrupted_job_older_than_the_last_200_rows_is_still_offered(tmp_path: Path, monkeypatch):
    from app import app as app_module
    from app.app import App
    from core.history import HistoryDB

    media = tmp_path / "old.mp4"
    media.write_bytes(b"x")
    db = HistoryDB(tmp_path / "history.db")
    try:
        old = db.insert_transcription(str(media))
        db.mark_interrupted()
        for i in range(210):
            rid = db.insert_transcription(str(tmp_path / f"n{i}.mp4"))
            db.finish_transcription(rid, "finished")
        monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *a, **k: True)
        ns = _ns_for_resume(db)
        App._maybe_offer_crash_resume(ns)  # type: ignore[arg-type]
        assert [t.file_path for t in ns.queue] == [str(media)]
        status = {r["id"]: r["status"] for r in db.list_transcriptions(1000)}[old]
        assert status == "cancelled"  # retired, so the next launch does not offer it again
    finally:
        db.close()
