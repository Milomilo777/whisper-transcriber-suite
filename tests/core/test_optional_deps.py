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


# --- C2.51b M5: free disk space is checked before pip runs -----------------


def _usage(free_mb: float):
    import types

    return types.SimpleNamespace(total=10 ** 12, used=0, free=int(free_mb * 1024 * 1024))


def test_install_refuses_a_full_disk_before_pip(monkeypatch, tmp_path):
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps.offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(optional_deps.shutil, "disk_usage", lambda _p: _usage(1000))

    def _no_popen(*_a, **_k):
        raise AssertionError("pip must not start on a full disk")

    monkeypatch.setattr(optional_deps.subprocess, "Popen", _no_popen)
    lines: list[str] = []
    assert optional_deps.install("alignment", log_cb=lines.append) is False
    assert any("Not enough free disk space" in line and str(final) in line for line in lines)


class _FinishedProc:
    """pip that already ran: it wrote a package into the staging dir."""

    def __init__(self, staging: str) -> None:
        pkg = os.path.join(staging, "bigpkg")
        os.makedirs(pkg)
        with open(os.path.join(pkg, "__init__.py"), "wb") as f:
            f.write(b"x" * (3 * 1024 * 1024))
        self.stdout = iter(())
        self.returncode = 0

    def wait(self, timeout=None):
        return 0


def test_merge_is_refused_when_the_staged_tree_does_not_fit(monkeypatch, tmp_path):
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps.offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(optional_deps, "_FEATURE_SIZE_MB", {"alignment": 1})
    # Room for the up-front estimate, not for copying the 3 MB staged tree.
    monkeypatch.setattr(optional_deps, "_FREE_SPACE_MARGIN_MB", 0)
    monkeypatch.setattr(optional_deps.shutil, "disk_usage", lambda _p: _usage(2.5))
    staged: dict = {}

    def _popen(cmd, **_k):
        staging = cmd[cmd.index("--target") + 1]
        staged["path"] = staging
        staged["cmd"], staged["kwargs"] = cmd, _k
        return _FinishedProc(staging)

    monkeypatch.setattr(optional_deps.subprocess, "Popen", _popen)
    lines: list[str] = []
    assert optional_deps.install("alignment", log_cb=lines.append) is False
    assert any("Not enough free disk space" in line for line in lines)
    # pip gets no stdin, and --no-input so a private-index login prompt fails
    # cleanly instead of raising EOFError.
    assert "--no-input" in staged["cmd"]
    assert staged["kwargs"]["stdin"] is optional_deps.subprocess.DEVNULL
    assert not os.path.exists(staged["path"])
    assert not (final / "bigpkg").exists()


def test_unreadable_disk_usage_does_not_block_the_install(monkeypatch, tmp_path):
    def _boom(_p):
        raise OSError("no such volume")

    monkeypatch.setattr(optional_deps.shutil, "disk_usage", _boom)
    assert optional_deps._has_room("alignment", str(tmp_path), 10 ** 9, None) is True


# --- C2.51b M6 / M7: installs from two processes; a package in use ----------


def test_install_lock_is_held_across_processes(tmp_path):
    import subprocess as sp
    import sys
    import textwrap

    root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    script = textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {root!r})
        from core import optional_deps as od
        with od._extras_file_lock({str(tmp_path)!r}, None, 30, None) as ok:
            print("held", ok, flush=True)
            sys.stdin.readline()
    """)
    child = sp.Popen([sys.executable, "-c", script], stdin=sp.PIPE, stdout=sp.PIPE, text=True)
    try:
        assert child.stdout is not None and child.stdin is not None
        assert child.stdout.readline().strip() == "held free"
        cancel = threading.Event()
        threading.Timer(0.4, cancel.set).start()
        lines: list[str] = []
        with optional_deps._extras_file_lock(str(tmp_path), cancel, 30, lines.append) as ok:
            assert ok == ""
        assert any("Another Whisper" in line for line in lines)
        stdin = child.stdin

        def _release() -> None:
            stdin.write("go\n")
            stdin.flush()

        threading.Timer(0.6, _release).start()
        # Waits for the other process, then gets the lock.
        with optional_deps._extras_file_lock(str(tmp_path), None, 30, None) as ok:
            assert ok == "waited"
    finally:
        child.kill() if child.poll() is None else None
        child.wait(10)


def test_a_package_in_use_asks_to_reopen_the_app(monkeypatch, tmp_path):
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps.offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(optional_deps, "_FEATURE_SIZE_MB", {"alignment": 1})
    monkeypatch.setattr(optional_deps.subprocess, "Popen",
                        lambda cmd, **_k: _FinishedProc(cmd[cmd.index("--target") + 1]))
    real_replace = os.replace

    def _locked(src, dst):
        if str(dst).endswith("bigpkg"):
            err = PermissionError(13, "The process cannot access the file")
            err.winerror = 32  # type: ignore[attr-defined]
            raise err
        return real_replace(src, dst)

    monkeypatch.setattr(optional_deps.os, "replace", _locked)
    lines: list[str] = []
    assert optional_deps.install("alignment", log_cb=lines.append) is False
    assert any("Close and reopen the app" in line for line in lines)

