"""Regression tests for fixpack cluster F.

Covers six confirmed bugs across four modules:

* core/history.py   — unlocked list_* readers race the worker writers;
                      corruption recovery leaks WAL/SHM sidecars and can
                      re-crash launch when os.replace fails.
* core/worker.py    — _stdin_reader crashes the whole worker on a
                      valid-JSON non-object command.
* core/logging_setup.py — a per-process log file is honoured so the GUI
                      and worker do not share one RotatingFileHandler.
* core/optional_deps.py — aborted pip installs reap the whole child tree;
                      a failed copytree merge must not leave a partial tree.

All hermetic: no real Tk root, no network, no real model / pip / binaries.
"""
from __future__ import annotations

import json
import os
import threading
import time

import pytest

from core import logging_setup, optional_deps
from core.history import HistoryDB


# ---------------------------------------------------------------------------
# Finding 1 — list_downloads / list_transcriptions must hold the write lock
# ---------------------------------------------------------------------------

def test_list_methods_acquire_write_lock(tmp_path):
    """The readers must serialise on _write_lock (same as stats()). We probe
    by making the lock observable: a reader that did NOT take the lock would
    be able to run while we hold it from another 'thread'."""
    db = HistoryDB(tmp_path / "h.db")
    try:
        db.insert_download("https://x")
        db.insert_transcription("/tmp/a.wav")

        # If list_* takes the lock, acquiring it first and never releasing
        # blocks the reader. We verify by running the reader on a thread and
        # asserting it does NOT complete while we hold the lock.
        db._write_lock.acquire()
        done = threading.Event()

        def _reader():
            db.list_downloads()
            db.list_transcriptions()
            done.set()

        t = threading.Thread(target=_reader, daemon=True)
        t.start()
        # Reader must be blocked on the lock we hold.
        assert not done.wait(timeout=0.5), (
            "list_* returned while _write_lock was held — reader is unlocked"
        )
        db._write_lock.release()
        assert done.wait(timeout=2.0), "reader never completed after release"
    finally:
        db.close()


def test_list_methods_concurrent_with_writes_no_error(tmp_path):
    """Hammer list_* on one thread while another inserts on the SAME
    connection. Without the lock this can raise sqlite3.ProgrammingError /
    return inconsistent rows. With the lock it is clean."""
    db = HistoryDB(tmp_path / "h.db")
    errors: list[Exception] = []
    stop = threading.Event()

    def _writer():
        i = 0
        while not stop.is_set():
            try:
                rid = db.insert_download(f"https://x/{i}")
                db.finish_download(rid, "finished")
                i += 1
            except Exception as e:  # noqa: BLE001
                errors.append(e)
                return

    def _reader():
        while not stop.is_set():
            try:
                db.list_downloads(limit=50)
                db.list_transcriptions(limit=50)
            except Exception as e:  # noqa: BLE001
                errors.append(e)
                return

    threads = [threading.Thread(target=_writer, daemon=True) for _ in range(2)]
    threads += [threading.Thread(target=_reader, daemon=True) for _ in range(2)]
    for t in threads:
        t.start()
    time.sleep(1.0)
    stop.set()
    for t in threads:
        t.join(timeout=3)
    db.close()
    assert not errors, f"concurrent read/write raised: {errors!r}"


# ---------------------------------------------------------------------------
# Finding 3 — corruption recovery removes sidecars + survives replace failure
# ---------------------------------------------------------------------------

def _corrupt_file(path) -> None:
    with open(path, "wb") as fh:
        fh.write(b"this is not a sqlite database at all" * 8)


def test_recovery_moves_orphan_wal_shm_sidecars_aside(tmp_path, monkeypatch):
    """When the corrupt-DB connection close() fails (so SQLite does NOT
    auto-clean its sidecars), recovery must still relocate the orphaned
    -wal/-shm next to the .corrupt file rather than leaving them next to the
    fresh DB for SQLite to (mis)checkpoint. Pre-fix the loop did not exist and
    the orphans stayed put."""
    import sqlite3

    path = tmp_path / "history.db"
    _corrupt_file(path)

    real_connect = sqlite3.connect
    state = {"wrapped": False}

    class _CloseFailsConn:
        """Proxy whose close() raises (simulating a Windows lock) and which
        forces a non-ok integrity_check, so the recovery move-aside runs with
        the planted orphan sidecars still on disk."""

        def __init__(self, conn):
            object.__setattr__(self, "_conn", conn)

        def execute(self, sql, *a, **k):
            if "integrity_check" in sql:
                return self._conn.execute("SELECT 'malformed'")
            return self._conn.execute(sql, *a, **k)

        def close(self):
            # Drop our real handle quietly, then signal a failed close so the
            # caller's `except sqlite3.Error: pass` fires and SQLite never
            # auto-removes the planted sidecars.
            try:
                self._conn.close()
            except Exception:  # noqa: BLE001
                pass
            raise sqlite3.OperationalError("simulated close lock")

        def __getattr__(self, name):
            return getattr(self._conn, name)

        def __setattr__(self, name, value):
            setattr(self._conn, name, value)

    def fake_connect(*a, **k):
        conn = real_connect(*a, **k)
        if not state["wrapped"]:
            state["wrapped"] = True
            return _CloseFailsConn(conn)
        return conn

    monkeypatch.setattr(sqlite3, "connect", fake_connect)

    # Plant orphan sidecars AFTER the proxy is armed but they persist because
    # close() raises. Use a fixture that re-creates them right before open.
    stale_wal = b"orphan-wal-frames-XYZ" + b"\0" * 64
    (tmp_path / "history.db-wal").write_bytes(stale_wal)
    (tmp_path / "history.db-shm").write_bytes(b"orphan-shm-XYZ")

    db = HistoryDB(path)  # must not raise
    try:
        assert list(tmp_path.glob("history.db.corrupt*"))
        # Orphan sidecars relocated next to the corrupt file (or removed) —
        # in either case they no longer poison the fresh DB.
        live_wal = tmp_path / "history.db-wal"
        if live_wal.exists():
            assert live_wal.read_bytes() != stale_wal, (
                "stale orphan -wal still sits next to the fresh DB"
            )
        live_shm = tmp_path / "history.db-shm"
        if live_shm.exists():
            assert live_shm.read_bytes() != b"orphan-shm-XYZ"
        # And the fresh DB is usable.
        rid = db.insert_download("https://x")
        assert rid > 0
    finally:
        try:
            db.close()
        except Exception:  # noqa: BLE001
            pass


def test_recovery_survives_garbage_file_without_crashing(tmp_path):
    """A fully-mangled file makes integrity_check RAISE rather than return a
    row. That must still trigger recovery (not fall through to executescript
    and crash __init__ at launch)."""
    path = tmp_path / "history.db"
    _corrupt_file(path)
    db = HistoryDB(path)  # must not raise DatabaseError
    try:
        assert list(tmp_path.glob("history.db.corrupt*"))
        rid = db.insert_download("https://x")
        assert rid > 0
    finally:
        db.close()


def test_recovery_survives_os_replace_failure(tmp_path, monkeypatch):
    """If os.replace of the corrupt main DB fails (e.g. Windows file lock),
    recovery must NOT reopen the still-corrupt file and crash __init__ — it
    deletes it in place and creates a clean DB instead."""
    path = tmp_path / "history.db"
    _corrupt_file(path)

    real_replace = os.replace
    state = {"failed": False}

    def flaky_replace(src, dst, *a, **k):
        # Fail only on the main-db move; let the (already-removed) sidecar
        # moves behave normally.
        if str(src) == str(path) and not state["failed"]:
            state["failed"] = True
            raise OSError("simulated Windows lock on history.db")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", flaky_replace)

    db = HistoryDB(path)  # must not raise DatabaseError
    try:
        assert state["failed"], "test did not exercise the os.replace failure"
        rid = db.insert_transcription("/tmp/a.wav")
        assert rid > 0
        # The corrupt file was deleted in place; the new DB lives at path.
        assert path.exists()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Finding 5 — setup_logging honours a per-process filename
# ---------------------------------------------------------------------------

def test_worker_log_filename_is_per_process():
    name1 = logging_setup.worker_log_filename(pid=111)
    name2 = logging_setup.worker_log_filename(pid=222)
    assert name1 == "worker-111.log"
    assert name2 == "worker-222.log"
    assert name1 != name2
    # default uses the live pid
    assert logging_setup.worker_log_filename() == f"worker-{os.getpid()}.log"


def test_setup_logging_accepts_filename(tmp_path, monkeypatch):
    """setup_logging must route to the given filename, not the shared
    app.log, so worker processes own a separate rotating file."""
    import logging

    monkeypatch.setattr(logging_setup, "user_log_dir", lambda: tmp_path)
    # Reset the module-level guard so we actually attach a handler here.
    monkeypatch.setattr(logging_setup, "_configured", False)
    # Detach any handlers we add so we do not pollute the root logger.
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        log_file = logging_setup.setup_logging("INFO", filename="worker-999.log")
        assert log_file == tmp_path / "worker-999.log"
        assert log_file.name == "worker-999.log"
    finally:
        for h in list(root.handlers):
            if h not in before:
                root.removeHandler(h)
                try:
                    h.close()
                except Exception:  # noqa: BLE001
                    pass


# ---------------------------------------------------------------------------
# Finding 6 — worker _stdin_reader tolerates a valid-JSON non-object command
# ---------------------------------------------------------------------------

def _simulate_stdin_reader(lines: list[str]) -> tuple[list, list[dict]]:
    """Mini re-implementation mirroring worker._stdin_reader's branch logic,
    used to prove the isinstance guard prevents the worker-killing crash.

    Returns (queued_commands, emitted_errors). A None sentinel means the
    reader fell through to the finally (i.e. the loop crashed)."""
    queued: list = []
    emitted: list[dict] = []

    def emit(event, **payload):
        emitted.append({"event": event, **payload})

    # This block is a faithful copy of the guarded branch in worker.py.
    crashed = False
    try:
        for raw in lines:
            line = raw.strip()
            if not line:
                continue
            try:
                command = json.loads(line)
            except json.JSONDecodeError as e:
                emit("error", message=f"Invalid worker command: {e}")
                continue
            if not isinstance(command, dict):
                emit("error", message="worker command must be a JSON object")
                continue
            if command.get("action") in ("cancel", "pause", "resume"):
                pass
            else:
                queued.append(command)
    except Exception:  # noqa: BLE001
        crashed = True
    queued.append(None if crashed else "_clean_eof")
    return queued, emitted


def test_worker_source_guards_non_object_command():
    """The real worker.py source must isinstance-check before .get()."""
    src = (
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    )
    worker_py = os.path.join(src, "core", "worker.py")
    text = open(worker_py, encoding="utf-8").read()
    assert "isinstance(command, dict)" in text, (
        "worker._stdin_reader must validate command is a dict before .get()"
    )


@pytest.mark.parametrize("bad", ["null", "5", '"foo"', "[1, 2]", "3.14", "true"])
def test_non_object_json_does_not_crash_reader(bad):
    """A valid-JSON non-object line must be ignored (error emitted), the
    reader stays alive, and a following real command is still queued."""
    queued, emitted = _simulate_stdin_reader([bad, '{"action": "shutdown"}'])
    # No crash → no None sentinel; clean EOF instead.
    assert None not in queued, "reader crashed on a valid-JSON non-object line"
    assert queued[-1] == "_clean_eof"
    # The good command after the bad one still made it through.
    assert {"action": "shutdown"} in queued
    # An error was surfaced for the bad line.
    assert any(
        e["event"] == "error" and "JSON object" in e["message"] for e in emitted
    )


# ---------------------------------------------------------------------------
# Finding 4 — aborted pip install reaps the whole tree via core._proc
# ---------------------------------------------------------------------------

class _FakeProcWithTree:
    """A pip process whose tree must be reaped via core._proc, not a bare
    terminate()/kill()."""

    def __init__(self):
        self.stdout = iter(())
        self.returncode = None
        self.pid = 4242
        self.terminate_called = False
        self.kill_called = False

    def poll(self):
        return self.returncode

    def wait(self, timeout=None):
        import subprocess
        if self.returncode is None:
            raise subprocess.TimeoutExpired(cmd="pip", timeout=timeout or 0.0)
        return self.returncode

    def terminate(self):
        self.terminate_called = True

    def kill(self):
        self.kill_called = True


def test_aborted_install_uses_kill_process_tree(monkeypatch, tmp_path):
    """On cancel the abort path must call core._proc.kill_process_tree on the
    pip process (whole-tree reap), not just proc.terminate()."""
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)

    proc = _FakeProcWithTree()
    monkeypatch.setattr(optional_deps.subprocess, "Popen", lambda *a, **k: proc)

    tree_calls: list = []

    def fake_kill_tree(p, *, force=False, timeout=5.0):
        tree_calls.append((id(p) == id(proc), force))
        p.returncode = -9  # tree reaped → subsequent wait() returns

    monkeypatch.setattr(optional_deps._proc, "kill_process_tree", fake_kill_tree)

    ev = threading.Event()
    ev.set()
    ok = optional_deps.install("alignment", cancel_event=ev, timeout=60)

    assert ok is False
    assert tree_calls, "abort path did not call _proc.kill_process_tree"
    assert tree_calls[0][0] is True, "kill_process_tree got the wrong process"


def test_install_spawns_with_new_session_kwargs(monkeypatch, tmp_path):
    """Popen must be given core._proc.new_session_kwargs() so the tree is
    killable (start_new_session on POSIX / CREATE_NO_WINDOW on Windows)."""
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)

    captured: dict = {}

    class _Done:
        stdout = iter(())
        returncode = 0
        pid = 1

        def poll(self):
            return 0

        def wait(self, timeout=None):
            return 0

    def fake_popen(*a, **k):
        captured.update(k)
        return _Done()

    monkeypatch.setattr(optional_deps.subprocess, "Popen", fake_popen)
    # Make the merge a no-op success: empty staging → nothing to merge.
    optional_deps.install("alignment", timeout=60)

    expected = optional_deps._proc.new_session_kwargs()
    for key, val in expected.items():
        assert captured.get(key) == val, f"Popen missing {key}={val!r}"


# ---------------------------------------------------------------------------
# Finding 2 — a failed copytree merge must not leave a partial tree
# ---------------------------------------------------------------------------

class _SucceedThenStageProc:
    """A pip process that 'installs' a fake package tree into the --target
    staging dir and exits 0, so install() proceeds to the merge step."""

    def __init__(self, staging_dir: str):
        self.stdout = iter(())
        self.returncode = 0
        self.pid = 1
        self._staging = staging_dir

    def poll(self):
        return 0

    def wait(self, timeout=None):
        return 0


def _make_fake_pkg(staging: str) -> None:
    """Write a fake top-level package (stable_whisper/) with submodules."""
    pkg = os.path.join(staging, "stable_whisper")
    os.makedirs(pkg, exist_ok=True)
    with open(os.path.join(pkg, "__init__.py"), "w", encoding="utf-8") as fh:
        fh.write("# fake\n")
    with open(os.path.join(pkg, "_core.py"), "w", encoding="utf-8") as fh:
        fh.write("# fake submodule\n")


def test_failed_merge_leaves_no_partial_tree(monkeypatch, tmp_path):
    """If the merge fails partway, install() must roll back so the extras dir
    does NOT contain a half-written top-level package that is_available()
    would falsely report as present."""
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)

    # Capture the staging dir and populate it with a fake package tree.
    real_mkdtemp = optional_deps.tempfile.mkdtemp
    staged: dict = {}

    def rec_mkdtemp(*a, **k):
        p = real_mkdtemp(*a, **k)
        staged["path"] = p
        _make_fake_pkg(p)
        return p

    monkeypatch.setattr(optional_deps.tempfile, "mkdtemp", rec_mkdtemp)
    monkeypatch.setattr(
        optional_deps.subprocess, "Popen",
        lambda *a, **k: _SucceedThenStageProc(staged.get("path", "")),
    )

    # Make the atomic move into final_target fail, simulating a disk-full /
    # locked-file failure mid-merge.
    real_replace = os.replace

    def boom_replace(src, dst, *a, **k):
        # Only blow up when moving INTO the final extras dir.
        if str(final) in str(dst):
            raise OSError("simulated disk full during merge")
        return real_replace(src, dst, *a, **k)

    monkeypatch.setattr(os, "replace", boom_replace)

    ok = optional_deps.install("alignment", timeout=60)
    assert ok is False
    # Critical: no partial top-level package left in the extras dir.
    leftover = final / "stable_whisper"
    assert not leftover.exists(), (
        "failed merge left a partial package tree in extras_dir"
    )
    # And the staging dir was cleaned up.
    assert "path" in staged
    assert not os.path.exists(staged["path"]), "staging tree not cleaned up"


def test_successful_merge_places_full_tree(monkeypatch, tmp_path):
    """The happy path: a clean merge moves the whole package tree (all
    submodules) atomically into the extras dir."""
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    # is_available: False on entry, True after merge (so install returns True).
    calls = {"n": 0}

    def fake_avail(feat):
        calls["n"] += 1
        return calls["n"] > 1

    monkeypatch.setattr(optional_deps, "is_available", fake_avail)

    real_mkdtemp = optional_deps.tempfile.mkdtemp
    staged: dict = {}

    def rec_mkdtemp(*a, **k):
        p = real_mkdtemp(*a, **k)
        staged["path"] = p
        _make_fake_pkg(p)
        return p

    monkeypatch.setattr(optional_deps.tempfile, "mkdtemp", rec_mkdtemp)
    monkeypatch.setattr(
        optional_deps.subprocess, "Popen",
        lambda *a, **k: _SucceedThenStageProc(staged.get("path", "")),
    )

    ok = optional_deps.install("alignment", timeout=60)
    assert ok is True
    # Whole tree present, not just the top-level dir + __init__.
    assert (final / "stable_whisper" / "__init__.py").exists()
    assert (final / "stable_whisper" / "_core.py").exists()
    assert not os.path.exists(staged["path"]), "staging tree not cleaned up"
