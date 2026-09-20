"""Tests for core._proc — cross-platform process-tree termination.

Validates audit findings [2]/[3]: killing a worker / yt-dlp must reach the
grandchild ffmpeg/demucs, not just the immediate child.
"""
from __future__ import annotations

import os

import pytest

from core import _proc


class _FakeProc:
    def __init__(self, pid=4321, alive=True):
        self.pid = pid
        self._alive = alive
        self.terminated = False
        self.killed = False

    def poll(self):
        return None if self._alive else 0

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


def test_new_session_kwargs_shape():
    kw = _proc.new_session_kwargs()
    if os.name == "nt":
        assert "creationflags" in kw
        assert "start_new_session" not in kw
    else:
        assert kw.get("start_new_session") is True


def test_kill_tree_none_is_noop():
    _proc.kill_process_tree(None)  # must not raise


def test_kill_tree_skips_exited_process(monkeypatch):
    calls = {"run": 0, "killpg": 0}
    monkeypatch.setattr(_proc.subprocess, "run", lambda *a, **k: calls.__setitem__("run", calls["run"] + 1))
    # os.killpg only exists on POSIX; raising=False keeps this portable.
    monkeypatch.setattr(
        _proc.os, "killpg",
        lambda *a, **k: calls.__setitem__("killpg", calls["killpg"] + 1),
        raising=False,
    )
    p = _FakeProc(alive=False)
    _proc.kill_process_tree(p, force=True)
    assert calls == {"run": 0, "killpg": 0}
    assert not p.terminated and not p.killed


@pytest.mark.skipif(os.name != "nt", reason="Windows taskkill path")
def test_kill_tree_windows_taskkill_args(monkeypatch):
    captured: dict = {}

    def fake_run(args, **kwargs):
        captured["args"] = list(args)
        captured["kwargs"] = kwargs

    monkeypatch.setattr(_proc.subprocess, "run", fake_run)

    _proc.kill_process_tree(_FakeProc(pid=4321), force=False)
    assert captured["args"][:3] == ["taskkill", "/PID", "4321"]
    assert "/T" in captured["args"]
    assert "/F" not in captured["args"]  # graceful

    captured.clear()
    _proc.kill_process_tree(_FakeProc(pid=99), force=True)
    assert "/F" in captured["args"]  # hard kill includes /F


@pytest.mark.skipif(os.name == "nt", reason="POSIX killpg path")
def test_kill_tree_posix_uses_killpg(monkeypatch):
    seen: dict = {}
    monkeypatch.setattr(_proc.os, "getpgid", lambda pid: pid)
    monkeypatch.setattr(_proc.os, "killpg", lambda pgid, sig: seen.update(pgid=pgid, sig=sig))
    _proc.kill_process_tree(_FakeProc(pid=555), force=True)
    assert seen["pgid"] == 555


def test_kill_tree_refuses_to_signal_its_own_process_group(monkeypatch):
    """Safety net: if a PID resolves into THIS process's own group (a call
    site that forgot new_session_kwargs(), or an OS-recycled PID), killpg
    would signal the app itself along with the tree. The helper must
    refuse and fall back to signalling just the parent."""
    monkeypatch.setattr(_proc.os, "name", "posix", raising=False)
    monkeypatch.setattr(_proc.os, "getpgid", lambda pid: 4242, raising=False)
    monkeypatch.setattr(_proc.signal, "SIGKILL", 9, raising=False)

    group_signals: list = []
    monkeypatch.setattr(
        _proc.os, "killpg",
        lambda pgid, sig: group_signals.append((pgid, sig)),
        raising=False,
    )

    p = _FakeProc(pid=4242)
    _proc.kill_process_tree(p, force=True)

    assert group_signals == [], "must never killpg the app's own group"
    assert p.killed is True, "parent-only fallback should still run"
