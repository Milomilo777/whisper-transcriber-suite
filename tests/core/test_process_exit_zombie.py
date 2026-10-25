"""pid_alive must not count a zombie as alive, also where /proc is absent
(macOS) and the zombie is not a child of this process.

The suite runs on Windows, so the POSIX branches are driven with mocks; one
real-process test runs only where fork-style POSIX processes exist.
"""
from __future__ import annotations

import subprocess
import sys
import time
import types

import pytest

from core import process_exit


def _no_proc(monkeypatch):
    real_open = open

    def _open(path, *a, **kw):
        if str(path).startswith("/proc/"):
            raise FileNotFoundError(path)
        return real_open(path, *a, **kw)

    monkeypatch.setattr("builtins.open", _open)
    monkeypatch.setattr(process_exit.sys, "platform", "darwin")
    monkeypatch.setattr(process_exit.os.path, "isdir", lambda p: False)


def _ps(monkeypatch, stdout="", exc=None):
    calls = []

    def _run(cmd, **kw):
        calls.append((cmd, kw))
        if exc is not None:
            raise exc
        return types.SimpleNamespace(stdout=stdout)

    monkeypatch.setattr(process_exit.subprocess, "run", _run)
    return calls


def _waitid_echild(monkeypatch):
    def _waitid(*_a):
        raise ChildProcessError(10, "No child processes")

    monkeypatch.setattr(process_exit.os, "waitid", _waitid, raising=False)
    for n, v in (("WEXITED", 4), ("WNOHANG", 1), ("WNOWAIT", 16777216), ("P_PID", 1)):
        monkeypatch.setattr(process_exit.os, n, v, raising=False)


def test_non_child_zombie_is_found_through_ps(monkeypatch):
    _no_proc(monkeypatch)
    _waitid_echild(monkeypatch)
    calls = _ps(monkeypatch, stdout="Z+\n")
    assert process_exit._is_zombie(4242) is True
    cmd, kw = calls[0]
    assert cmd == ["ps", "-o", "stat=", "-p", "4242"]
    assert not kw.get("shell") and kw.get("timeout")


def test_running_non_child_is_not_a_zombie(monkeypatch):
    _no_proc(monkeypatch)
    _waitid_echild(monkeypatch)
    _ps(monkeypatch, stdout="Ss\n")
    assert process_exit._is_zombie(4242) is False


@pytest.mark.parametrize("exc", [
    FileNotFoundError("ps"),
    subprocess.TimeoutExpired("ps", 2.0),
])
def test_ps_failure_means_not_known_zombie(monkeypatch, exc):
    _no_proc(monkeypatch)
    _waitid_echild(monkeypatch)
    _ps(monkeypatch, exc=exc)
    assert process_exit._is_zombie(4242) is False


def test_exited_child_still_found_by_waitid_without_ps(monkeypatch):
    _no_proc(monkeypatch)
    for n, v in (("WEXITED", 4), ("WNOHANG", 1), ("WNOWAIT", 16777216), ("P_PID", 1)):
        monkeypatch.setattr(process_exit.os, n, v, raising=False)
    monkeypatch.setattr(process_exit.os, "waitid", lambda *a: object(), raising=False)
    calls = _ps(monkeypatch, stdout="S\n")
    assert process_exit._is_zombie(4242) is True
    assert calls == []


def test_linux_with_proc_never_spawns_ps(monkeypatch):
    # Linux has /proc: a vanished entry means gone, not "ask ps".
    monkeypatch.setattr(process_exit.sys, "platform", "linux")
    _waitid_echild(monkeypatch)
    calls = _ps(monkeypatch, stdout="Z\n")
    assert process_exit._is_zombie(2 ** 22 + 12345) is False
    assert calls == []


@pytest.mark.skipif(sys.platform == "win32" or not hasattr(__import__("os"), "fork"),
                    reason="needs POSIX processes")
def test_real_non_child_zombie_is_not_alive():
    # Grandchild exits while its parent (the middle process) stays alive without
    # reaping it: from here it is a zombie that is not our child.
    code = (
        "import os,sys,time\n"
        "pid=os.fork()\n"
        "if pid==0:\n"
        "    os._exit(0)\n"
        "print(pid, flush=True)\n"
        "time.sleep(30)\n"
    )
    mid = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    try:
        assert mid.stdout is not None
        grandchild = int(mid.stdout.readline())
        deadline = time.monotonic() + 5
        while process_exit.pid_alive(grandchild) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert process_exit.pid_alive(grandchild) is False
    finally:
        mid.kill()
        mid.wait()
