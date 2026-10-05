"""Fixpack J regression tests.

Two CONFIRMED bugs, both hermetic (no real Tk, no network, no real process):

  * core._proc.kill_process_tree(force=False) on Windows ran a graceful
    ``taskkill /T`` (no /F) and swallowed its non-zero exit. Windowless
    console trees (yt-dlp + its ffmpeg merge child) ignore the WM_CLOSE a
    graceful taskkill posts, so the tree survived and the download
    Cancel/Pause/close paths orphaned it (holding the .part/output handle).
    The fix escalates to ``taskkill /T /F`` when the graceful pass reports
    failure, while keeping force=True unchanged and keeping the graceful
    FIRST call /F-free.

  * core.stats.post_stats_async passed config['stats_url'] straight to
    urlopen with no scheme check. stats_url is in ONLINE_ALLOWED_KEYS (it is
    remotely settable via the fetched online config), so a non-http(s) scheme
    must be rejected before the request.

These tests FORCE the Windows branch of _proc with an ``_NtOs`` proxy (the
same trick tests/core/test_macos_cross_platform.py uses for POSIX) so they
run identically on any host without mutating the real os.name (which would
break pathlib on Windows).
"""
from __future__ import annotations

import os

import pytest

from core import _proc, stats


# --------------------------------------------------------------------------- #
#  helpers
# --------------------------------------------------------------------------- #
class _NtOs:
    """Proxy to the real ``os`` that reports ``name == 'nt'``.

    Flips only ``_proc``'s ``os.name == "nt"`` guard onto the Windows branch;
    everything else forwards to the real os, and pathlib is untouched.
    """

    name = "nt"

    def __getattr__(self, item):
        return getattr(os, item)


def _force_nt(monkeypatch):
    monkeypatch.setattr(_proc, "os", _NtOs())


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


class _Result:
    """Stand-in for the CompletedProcess returned by subprocess.run."""

    def __init__(self, returncode):
        self.returncode = returncode


def _record_run(monkeypatch, returncodes):
    """Patch _proc.subprocess.run to record args and return scripted codes.

    ``returncodes`` is consumed left to right; runs past its end return rc 0.
    """
    calls: list[list[str]] = []
    seq = list(returncodes)

    def fake_run(args, **kwargs):
        calls.append(list(args))
        rc = seq.pop(0) if seq else 0
        return _Result(rc)

    monkeypatch.setattr(_proc.subprocess, "run", fake_run)
    return calls


# --------------------------------------------------------------------------- #
#  _proc — Windows graceful->forced escalation
# --------------------------------------------------------------------------- #
def test_graceful_taskkill_failure_escalates_to_force(monkeypatch):
    """A non-zero graceful taskkill must trigger a second /T /F kill."""
    _force_nt(monkeypatch)
    calls = _record_run(monkeypatch, returncodes=[1, 0])  # graceful fails, /F ok

    _proc.kill_process_tree(_FakeProc(pid=4321), force=False)

    assert len(calls) == 2, "graceful failure should escalate to a 2nd call"
    # First call is the graceful tree-kill: /T but NOT /F.
    assert calls[0][:3] == ["taskkill", "/PID", "4321"]
    assert "/T" in calls[0] and "/F" not in calls[0]
    # Second call escalates: /T AND /F.
    assert "/T" in calls[1] and "/F" in calls[1]
    assert calls[1][:3] == ["taskkill", "/PID", "4321"]


def test_graceful_taskkill_success_does_not_escalate(monkeypatch):
    """When the graceful taskkill returns 0, no /F escalation happens."""
    _force_nt(monkeypatch)
    calls = _record_run(monkeypatch, returncodes=[0])

    _proc.kill_process_tree(_FakeProc(pid=4321), force=False)

    assert len(calls) == 1
    assert "/F" not in calls[0]


def test_force_true_is_single_forced_call(monkeypatch):
    """force=True still issues exactly one /F call (no double-kill)."""
    _force_nt(monkeypatch)
    calls = _record_run(monkeypatch, returncodes=[1])  # rc ignored when force

    _proc.kill_process_tree(_FakeProc(pid=99), force=True)

    assert len(calls) == 1
    assert "/F" in calls[0] and "/T" in calls[0]


def test_graceful_none_result_does_not_escalate(monkeypatch):
    """A run() that returns None (no returncode) must not crash or escalate.

    This mirrors the existing test_proc.py fake_run that returns None; the
    escalation guard treats a non-int returncode as 'do not escalate'.
    """
    _force_nt(monkeypatch)
    calls: list[list[str]] = []
    monkeypatch.setattr(
        _proc.subprocess, "run",
        lambda args, **k: calls.append(list(args)),  # returns None
    )

    _proc.kill_process_tree(_FakeProc(pid=4321), force=False)

    assert len(calls) == 1
    assert "/F" not in calls[0]


def test_escalation_exception_falls_back_to_parent_terminate(monkeypatch):
    """If the escalated /F run raises, the last-resort parent signal runs."""
    _force_nt(monkeypatch)
    state = {"n": 0}

    def fake_run(args, **kwargs):
        state["n"] += 1
        if state["n"] == 1:
            return _Result(1)  # graceful fails -> escalate
        raise OSError("boom")  # the /F escalation blows up

    monkeypatch.setattr(_proc.subprocess, "run", fake_run)
    p = _FakeProc(pid=4321)

    _proc.kill_process_tree(p, force=False)  # must not raise

    # force=False -> last resort is terminate(), not kill().
    assert p.terminated is True
    assert p.killed is False


def test_exited_process_is_not_touched(monkeypatch):
    """An already-exited process triggers no taskkill at all (regression)."""
    _force_nt(monkeypatch)
    calls = _record_run(monkeypatch, returncodes=[1, 1])
    _proc.kill_process_tree(_FakeProc(alive=False), force=False)
    assert calls == []


# --------------------------------------------------------------------------- #
#  stats — reject non-http(s) stats_url before urlopen
# --------------------------------------------------------------------------- #
def _payload():
    return stats.build_stats_payload(
        model="m", language="en",
        audio_duration=1.0, transcription_time=1.0, status="finished",
    )


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///etc/passwd",
        "ftp://attacker.example/collect",
        "gopher://x/y",
        "javascript:alert(1)",
        "//attacker.example/collect",   # scheme-relative -> empty scheme
        "attacker.example/collect",     # bare host -> empty scheme
    ],
)
def test_non_http_scheme_is_rejected(monkeypatch, bad_url):
    """A non-http(s) stats_url must NOT start a POST thread."""
    started = {"n": 0}
    monkeypatch.setattr(
        stats, "_post",
        lambda *a, **k: started.__setitem__("n", started["n"] + 1),
    )
    cfg = {"telemetry_opt_in": True, "stats_url": bad_url}
    assert stats.post_stats_async(cfg, _payload()) is False
    assert started["n"] == 0


@pytest.mark.parametrize(
    "good_url",
    [
        "http://example.com/s.php",
        "https://example.com/s.php",
        "HTTPS://example.com/s.php",   # scheme is lower-cased by urlsplit
    ],
)
def test_http_and_https_are_accepted(monkeypatch, good_url):
    """http / https stats_url is accepted and the POST is dispatched."""
    seen: dict = {}

    def fake_post(url, payload, timeout):
        seen["url"] = url

    monkeypatch.setattr(stats, "_post", fake_post)
    cfg = {"telemetry_opt_in": True, "stats_url": good_url}
    assert stats.post_stats_async(cfg, _payload(), timeout=1.0) is True
    import time as _t
    for _ in range(50):
        if "url" in seen:
            break
        _t.sleep(0.01)
    assert seen.get("url") == good_url
