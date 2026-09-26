"""Tests for core.optional_deps (on-demand optional dependency mechanism)."""
from __future__ import annotations

import os
import subprocess
import threading

from core import optional_deps


def test_packages_for_known_features():
    assert optional_deps.packages_for("alignment") == ["stable-ts"]
    assert optional_deps.packages_for("whisper_backend") == ["openai-whisper"]


def test_packages_for_unknown_feature_is_empty():
    assert optional_deps.packages_for("nope") == []


def test_extras_dir_ends_in_pylibs():
    assert optional_deps.extras_dir().replace("\\", "/").endswith("/pylibs")


def test_is_available_unknown_feature_is_false():
    # An unknown feature has no module to probe → never available, no raise.
    assert optional_deps.is_available("definitely-not-a-real-feature") is False


def test_install_unknown_feature_is_noop_false():
    # No packages → nothing to install, returns False without spawning pip.
    assert optional_deps.install("nope") is False


class _FakeHangingProc:
    """A pip process that never finishes on its own (simulates a stalled
    PyPI / proxy black-hole) but exits cleanly once terminated."""

    def __init__(self):
        self.stdout = iter(())  # pump thread exits immediately
        self.returncode = None
        self._killed = False

    def wait(self, timeout=None):
        if self._killed:
            self.returncode = -9
            return self.returncode
        raise subprocess.TimeoutExpired(cmd="pip", timeout=timeout or 0.0)

    def terminate(self):
        self._killed = True

    def kill(self):
        self._killed = True


def test_install_cancel_terminates_pip_and_cleans_staging(monkeypatch, tmp_path):
    """[11]: a cancelled install must terminate pip, return False, and leave
    no half-written staging tree behind."""
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)

    staged: dict = {}
    real_mkdtemp = optional_deps.tempfile.mkdtemp

    def rec_mkdtemp(*a, **k):
        p = real_mkdtemp(*a, **k)
        staged["path"] = p
        return p

    monkeypatch.setattr(optional_deps.tempfile, "mkdtemp", rec_mkdtemp)
    monkeypatch.setattr(
        optional_deps.subprocess, "Popen", lambda *a, **k: _FakeHangingProc()
    )

    ev = threading.Event()
    ev.set()  # pre-cancelled: the first poll iteration aborts
    ok = optional_deps.install("alignment", cancel_event=ev, timeout=60)

    assert ok is False
    assert "path" in staged
    assert not os.path.exists(staged["path"]), "staging tree must be cleaned up"


def test_install_timeout_aborts(monkeypatch, tmp_path):
    """[11]: a stalled pip is bounded by the timeout, not left to hang."""
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)
    monkeypatch.setattr(
        optional_deps.subprocess, "Popen", lambda *a, **k: _FakeHangingProc()
    )
    # timeout=0 → the deadline is immediately in the past on the first poll.
    # (DEFAULT path uses a real 1800s cap; 0 disables only the deadline, so
    # pass a tiny positive value to exercise the timeout branch.)
    ok = optional_deps.install("alignment", timeout=0.01)
    assert ok is False


def test_install_refuses_in_a_frozen_app_without_running_pip(monkeypatch):
    """A PyInstaller .app has no pip: sys.executable is the app itself."""
    import sys

    from core import optional_deps

    monkeypatch.setattr(sys, "frozen", True, raising=False)

    def _no_popen(*_a, **_k):
        raise AssertionError("pip must not be started in a frozen app")

    monkeypatch.setattr(optional_deps.subprocess, "Popen", _no_popen)
    logged: list[str] = []
    assert optional_deps.can_install() is False
    assert optional_deps.install("alignment", log_cb=logged.append) is False
    assert logged == [optional_deps.FROZEN_INSTALL_MESSAGE]
