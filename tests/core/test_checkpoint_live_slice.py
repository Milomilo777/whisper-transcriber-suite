"""Startup cleanup must not remove a long-running worker's decoded input."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import wave

from core import _checkpoint as cp


def test_old_slice_owned_by_live_child_is_retained_then_cleaned_after_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    key = cp.source_key(str(tmp_path / "source.wav"))
    ready = tmp_path / "ready.json"
    script = r"""
import json, os, sys, threading, wave
from pathlib import Path
folder, key, ready = sys.argv[1:]
path = Path(folder) / (key + '.' + str(os.getpid()) + '-' + str(threading.get_ident()) + '.slice.wav')
with wave.open(str(path), 'wb') as stream:
    stream.setnchannels(1)
    stream.setsampwidth(2)
    stream.setframerate(16000)
    stream.writeframes(b'\0\0' * 1600)
Path(ready).write_text(json.dumps({'path': str(path), 'pid': os.getpid()}), encoding='utf-8')
sys.stdin.read(1)
"""
    process = subprocess.Popen([(getattr(sys, "_base_executable", None) or sys.executable), "-c", script, str(tmp_path), key, str(ready)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists():
            assert process.poll() is None, "the native slice owner exited before readiness"
            assert time.monotonic() < deadline
            time.sleep(0.01)
        info = json.loads(ready.read_text(encoding="utf-8"))
        path = Path(info["path"])
        assert info["pid"] == process.pid and process.poll() is None
        with wave.open(str(path), "rb") as stream:
            assert stream.getnframes() == 1600
        original = path.read_bytes()
        os.utime(path, (1, 1))
        assert cp.sweep_partials() == 0
        assert path.read_bytes() == original
        stdout, stderr = process.communicate(input="x", timeout=5)
        assert process.returncode == 0, (stdout, stderr)
        assert cp.sweep_partials() == 1
        assert not path.exists()
    finally:
        if process.poll() is None:
            process.terminate()
            process.communicate(timeout=5)


def test_unknown_owner_of_legacy_slice_is_not_assumed_dead(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    path = tmp_path / (cp.source_key("legacy-source.wav") + ".slice.wav")
    path.write_bytes(b"legacy decoded input whose owner is unknown")
    os.utime(path, (1, 1))
    assert cp.sweep_partials() == 0
    assert path.read_bytes() == b"legacy decoded input whose owner is unknown"


def test_process_lookup_uncertainty_keeps_slice(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core import _proc
    path = tmp_path / (cp.source_key("uncertain.wav") + ".123-456.slice.wav")
    path.write_bytes(b"possibly active input")
    os.utime(path, (1, 1))
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    for failure in (PermissionError("synthetic denied process lookup"), OSError("synthetic process query failure")):
        def fail(pid):
            raise failure
        monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(pid_exists=fail))
        assert _proc.pid_may_be_alive(123)
        assert cp.sweep_partials() == 0
        assert path.read_bytes() == b"possibly active input"


def test_missing_psutil_keeps_slice(tmp_path, monkeypatch):
    from core import _proc
    path = tmp_path / (cp.source_key("missing-module.wav") + ".123-456.slice.wav")
    path.write_bytes(b"unknown process owner")
    os.utime(path, (1, 1))
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "psutil", None)
    assert _proc.pid_may_be_alive(123)
    assert cp.sweep_partials() == 0
    assert path.read_bytes() == b"unknown process owner"


def test_fresh_slice_never_needs_process_query(tmp_path, monkeypatch):
    path = tmp_path / (cp.source_key("fresh.wav") + ".123-456.slice.wav")
    path.write_bytes(b"fresh decode")
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    def unexpected(pid):
        raise AssertionError("fresh files must not reach the PID check")
    attempts = []
    def query(pid):
        attempts.append(pid)
        return unexpected(pid)
    monkeypatch.setattr("core._proc.pid_may_be_alive", query)
    assert cp.sweep_partials() == 0
    assert attempts == []
    assert path.read_bytes() == b"fresh decode"


def test_unknown_or_reused_pid_is_kept_without_signalling_any_process(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core import _proc
    path = tmp_path / (cp.source_key("reused.wav") + ".123.slice.wav")
    path.write_bytes(b"old but possibly in use")
    os.utime(path, (1, 1))
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    observed = []
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(pid_exists=lambda pid: observed.append(pid) or True))
    assert cp.sweep_partials() == 0
    assert observed == [123]
    assert path.read_bytes() == b"old but possibly in use"
    assert _proc.pid_may_be_alive(0)
    assert _proc.pid_may_be_alive(-1)


def test_non_boolean_process_probe_does_not_authorize_cleanup(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from core import _proc
    path = tmp_path / (cp.source_key("uncertain-result.wav") + ".123.slice.wav")
    path.write_bytes(b"unknown owner state")
    os.utime(path, (1, 1))
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(pid_exists=lambda pid: None))
    assert _proc.pid_may_be_alive(123)
    assert cp.sweep_partials() == 0
    assert path.read_bytes() == b"unknown owner state"
