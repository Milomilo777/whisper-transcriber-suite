"""Worker processes never outlive the app; the updater never leaves a child.

* The transcription worker cancels a task in flight (paused included) when
  the app goes away, so it saves its checkpoint and exits.
* The voice-clone worker exits mid-generation when the app is gone.
* A timed-out yt-dlp update ends the whole process tree.
* Only one app instance may flip running history rows to interrupted.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from core import _proc, worker
from core.history import HistoryDB


# ------------------------------------------------- transcription worker


class _StdinUntil:
    """stdin stand-in: yields ``lines``, then blocks until ``eof`` is set,
    then reports EOF (the app went away)."""

    def __init__(self, lines: list[str], eof: threading.Event) -> None:
        self._buf = io.StringIO("".join(lines))
        self._eof = eof

    def read(self, n: int = -1) -> str:
        chunk = self._buf.read(n)
        if chunk:
            return chunk
        self._eof.wait(10)
        return ""


def test_worker_cancels_a_paused_task_and_exits_when_the_app_goes(monkeypatch, capsys):
    paused = threading.Event()
    seen: dict[str, object] = {}

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        task.paused = True  # the user pressed Pause
        paused.set()
        deadline = time.monotonic() + 8
        while task.paused and not task.cancelled and time.monotonic() < deadline:
            time.sleep(0.02)
        seen["cancelled"] = task.cancelled

    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", fake_transcribe)
    monkeypatch.setattr(worker, "_hard_exit", lambda code: pytest.fail("backstop fired"))
    monkeypatch.setattr(_proc, "parent_alive", lambda identity: False)  # the app died
    cmd = json.dumps({"action": "transcribe", "file_path": "x.wav", "task_id": "t1"}) + "\n"
    monkeypatch.setattr(sys, "stdin", _StdinUntil([cmd], paused))

    t0 = time.monotonic()
    assert worker.main() == 0
    assert seen.get("cancelled") is True
    assert time.monotonic() - t0 < 6
    # Everything is disarmed once main() returns.
    assert worker._parent_lost_timer is None and not worker._parent_lost.is_set()
    assert not worker._session_active


def test_a_task_registered_after_the_app_went_away_is_cancelled():
    task = types.SimpleNamespace(task_id="", cancelled=False, paused=False)
    worker._begin_session()
    try:
        worker._mark_parent_lost("test")
        worker._register_task(task)  # type: ignore[arg-type]
        assert task.cancelled is True
    finally:
        worker._set_current_task(None)
        worker._end_session()


def test_eof_after_main_returned_arms_nothing():
    # A shutdown ends main() before the stdin reader reaches EOF.
    worker._end_session()
    worker._mark_parent_lost("test")
    assert not worker._parent_lost.is_set() and worker._parent_lost_timer is None


def test_parent_loss_backstop_exits_a_worker_that_never_returns(monkeypatch):
    exited = threading.Event()
    monkeypatch.setattr(worker, "PARENT_LOST_EXIT_GRACE_S", 0.05)
    monkeypatch.setattr(worker, "_hard_exit", lambda code: exited.set())
    worker._begin_session()
    try:
        worker._mark_parent_lost("test")
        assert exited.wait(3)
    finally:
        worker._end_session()


def test_a_closed_pipe_while_the_app_still_runs_cancels_nothing(monkeypatch, capsys):
    """A finite stdin (EOF) with a living parent keeps the old behaviour."""
    seen: list[bool] = []
    monkeypatch.setattr(worker, "PARENT_GONE_CONFIRM_S", 0.3)
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        time.sleep(0.8)  # still running when the pipe check gives up
        seen.append(task.cancelled)

    monkeypatch.setattr(worker, "transcribe", fake_transcribe)
    monkeypatch.setattr(sys, "stdin", io.StringIO(
        json.dumps({"action": "transcribe", "file_path": "x.wav"}) + "\n"))
    assert worker.main() == 0
    assert seen == [False] and worker._parent_lost_timer is None


# ------------------------------------------------- voice-clone worker


def _fake_voice_clone(monkeypatch, generate):
    fake = types.ModuleType("core.voice_clone")
    fake.load_model = lambda device: object()  # type: ignore[attr-defined]
    fake.generate = generate  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "core.voice_clone", fake)
    import core

    monkeypatch.setattr(core, "voice_clone", fake, raising=False)


def test_voice_worker_exits_mid_generation_when_the_app_is_gone(monkeypatch, capsys):
    from core import voice_clone_worker as vw

    generating = threading.Event()
    exited = threading.Event()

    def generate(*a, **k):
        generating.set()
        exited.wait(8)  # blocks like OmniVoice until the process ends
        raise RuntimeError("process ended")

    _fake_voice_clone(monkeypatch, generate)
    monkeypatch.setattr(vw, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(vw, "parent_alive", lambda identity: False)
    monkeypatch.setattr(_proc, "parent_alive", lambda identity: False)
    monkeypatch.setattr(vw, "_hard_exit", lambda code: exited.set())
    cmd = json.dumps({"action": "generate", "id": "r1", "text": "hi"}) + "\n"
    monkeypatch.setattr(sys, "stdin", _LineStdin([cmd], generating))
    assert vw.main() == 0
    assert exited.is_set()


def test_voice_worker_finishes_when_the_app_is_still_there(monkeypatch, capsys):
    from core import voice_clone_worker as vw

    generating = threading.Event()

    def generate(*a, **k):
        generating.set()
        time.sleep(0.2)
        return types.SimpleNamespace(output_path="o.wav", audio_seconds=1.0,
                                     elapsed_seconds=0.2, warning="")

    _fake_voice_clone(monkeypatch, generate)
    monkeypatch.setattr(vw, "setup_logging", lambda *a, **k: None)
    monkeypatch.setattr(vw, "parent_alive", lambda identity: True)
    monkeypatch.setattr(_proc, "parent_alive", lambda identity: True)
    monkeypatch.setattr(vw, "_hard_exit", lambda code: pytest.fail("must not exit"))
    cmd = json.dumps({"action": "generate", "id": "r1", "text": "hi"}) + "\n"
    monkeypatch.setattr(sys, "stdin", _LineStdin([cmd], generating))
    assert vw.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [e["event"] for e in events if e["event"] == "done"] == ["done"]


def test_parent_check_tells_a_reused_pid_from_the_parent():
    pytest.importorskip("psutil")
    from core._proc import parent_alive, parent_identity

    me = parent_identity()
    assert me is not None and parent_alive(me)
    assert not parent_alive((me[0], me[1] + 1000.0))  # same PID, newer process
    assert parent_alive(None)  # unknown -> never exit on a guess


class _LineStdin:
    """Line-iterable stdin: yields ``lines``, then EOF once ``eof`` is set."""

    def __init__(self, lines: list[str], eof: threading.Event) -> None:
        self._lines = list(lines)
        self._eof = eof

    def __iter__(self):
        yield from self._lines
        self._eof.wait(10)


# ------------------------------------------------- yt-dlp updater


_GRANDPARENT = (
    "import subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
    "open(sys.argv[1], 'w').write(str(child.pid))\n"
    "time.sleep(60)\n"
)


def test_update_timeout_kills_the_whole_tree(tmp_path: Path):
    psutil = pytest.importorskip("psutil")
    from core import yt_dlp_update as ydu

    pid_file = tmp_path / "child.pid"
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        ydu.run_killing_tree(
            [sys.executable, "-c", _GRANDPARENT, str(pid_file)],
            timeout=3, capture_output=True, text=True, stdin=subprocess.DEVNULL,
        )
    # subprocess.run only returned once the child ended by itself (~60 s):
    # the "timeout" let the update run on.
    assert time.monotonic() - t0 < 30
    child = int(pid_file.read_text())
    deadline = time.monotonic() + 10
    alive = True
    while time.monotonic() < deadline:
        try:
            alive = psutil.Process(child).status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            alive = False
        if not alive:
            break
        time.sleep(0.1)
    if alive:  # do not leak it into the rest of the run
        psutil.Process(child).kill()
    assert not alive, "the update's child process outlived the timeout"


def test_run_killing_tree_returns_like_subprocess_run():
    from core import yt_dlp_update as ydu

    proc = ydu.run_killing_tree(
        [sys.executable, "-c", "print('hi')"], timeout=30,
        capture_output=True, text=True, stdin=subprocess.DEVNULL,
    )
    assert proc.returncode == 0 and proc.stdout.strip() == "hi"


def test_the_updater_uses_the_tree_killing_runner_by_default():
    import inspect

    from core import yt_dlp_update as ydu

    default = inspect.signature(ydu.update_cached_copy).parameters["run"].default
    assert default is ydu.run_killing_tree


# ------------------------------------------------- history instance lock


def test_a_second_instance_leaves_the_first_ones_running_rows_alone(tmp_path: Path):
    first = HistoryDB(tmp_path / "history.db")
    second = HistoryDB(tmp_path / "history.db")
    try:
        assert first.mark_interrupted_on_launch() == 0
        rid = first.insert_transcription(str(tmp_path / "talk.mp4"))
        assert second.mark_interrupted_on_launch() is None
        rows = {r["id"]: r["status"] for r in second.list_transcriptions()}
        assert rows[rid] == "running"
    finally:
        first.close()
        second.close()


def test_the_instance_lock_is_free_again_once_the_owner_closes(tmp_path: Path):
    first = HistoryDB(tmp_path / "history.db")
    rid = first.insert_transcription(str(tmp_path / "talk.mp4"))
    assert first.claim_instance_lock()
    first.close()  # the owning app ended (a crash frees the OS lock too)
    later = HistoryDB(tmp_path / "history.db")
    try:
        assert later.mark_interrupted_on_launch() == 1
        rows = {r["id"]: r["status"] for r in later.list_transcriptions()}
        assert rows[rid] == "interrupted"
    finally:
        later.close()


def test_the_instance_lock_is_held_against_another_process(tmp_path: Path):
    db_path = tmp_path / "history.db"
    owner = HistoryDB(db_path)
    try:
        assert owner.claim_instance_lock()
        code = (
            "import sys; sys.path.insert(0, sys.argv[2]);"
            "from core.history import HistoryDB;"
            "db = HistoryDB(sys.argv[1]); print(db.claim_instance_lock()); db.close()"
        )
        repo = str(Path(__file__).resolve().parents[2])
        out = subprocess.run(
            [sys.executable, "-c", code, str(db_path), repo],
            capture_output=True, text=True, timeout=60, cwd=repo,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        assert out.stdout.strip() == "False", out.stderr
    finally:
        owner.close()


def test_a_filesystem_without_locks_does_not_freeze_running_rows(tmp_path: Path, monkeypatch):
    import errno

    def no_locks(*a, **k):
        raise OSError(errno.ENOLCK if hasattr(errno, "ENOLCK") else errno.EINVAL, "no locks")

    if sys.platform == "win32":
        import msvcrt
        monkeypatch.setattr(msvcrt, "locking", no_locks)
    else:
        import fcntl
        monkeypatch.setattr(fcntl, "flock", no_locks)
    db = HistoryDB(tmp_path / "history.db")
    try:
        db.insert_transcription(str(tmp_path / "talk.mp4"))
        assert db.mark_interrupted_on_launch() == 1
    finally:
        db.close()


def test_a_zombie_parent_counts_as_gone(monkeypatch):
    psutil = pytest.importorskip("psutil")

    class Zombie:
        def __init__(self, pid):
            raise psutil.ZombieProcess(pid)

    monkeypatch.setattr(psutil, "Process", Zombie)
    assert _proc.parent_alive((12345, 1.0)) is False
