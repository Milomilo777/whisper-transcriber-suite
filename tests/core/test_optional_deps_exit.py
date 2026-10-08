"""An app exit stops pip installs cleanly and waits for the merge phase.

``end_process`` ends the process at once, so an install thread cut inside its merge phase
(``os.replace`` + ``.bak`` moves) or its staging cleanup could leave a ``.<name>.bak-<pid>``
and a missing package. The exit now (1) asks every running install to stop (pip is killed and
its staging removed, whichever window started the install) and (2) waits, bounded, until
no install is left in ``install()``.
"""
from __future__ import annotations

import os
import subprocess
import threading
import types
from pathlib import Path
from typing import Any

import pytest

from app import app as app_module
from app.app import App
from core import optional_deps


@pytest.fixture(autouse=True)
def _fresh_stop_flag() -> Any:
    optional_deps._stop_requested.clear()
    yield
    optional_deps._stop_requested.clear()


def _env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    final = tmp_path / "pylibs"
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(final))
    monkeypatch.setattr(optional_deps, "is_available", lambda feat: False)
    monkeypatch.setattr(optional_deps, "can_install", lambda: True)
    monkeypatch.setattr(optional_deps.offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(optional_deps, "_FEATURE_SIZE_MB", {"alignment": 1})
    return final


class _HangingProc:
    def __init__(self) -> None:
        self.stdout = iter(())
        self.returncode: int | None = None
        self._killed = False

    def wait(self, timeout: float | None = None) -> int:
        if self._killed:
            self.returncode = -9
            return -9
        raise subprocess.TimeoutExpired(cmd="pip", timeout=timeout or 0.0)

    def terminate(self) -> None:
        self._killed = True

    def kill(self) -> None:
        self._killed = True


class _FinishedProc:
    def __init__(self, staging: str) -> None:
        pkg = os.path.join(staging, "bigpkg")
        os.makedirs(pkg)
        Path(pkg, "__init__.py").write_bytes(b"x" * 1024)
        self.stdout = iter(())
        self.returncode = 0

    def wait(self, timeout: float | None = None) -> int:
        return 0


def test_idle_when_nothing_is_installing() -> None:
    assert optional_deps.wait_until_idle(0.0) is True
    assert optional_deps.installs_merging() is False


def test_the_exit_request_aborts_a_running_pip_and_removes_its_staging(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _env(monkeypatch, tmp_path)
    monkeypatch.setattr(optional_deps.subprocess, "Popen", lambda *a, **k: _HangingProc())
    staged: dict[str, str] = {}
    real_mkdtemp = optional_deps.tempfile.mkdtemp

    def _mk(*a: Any, **k: Any) -> str:
        staged["path"] = real_mkdtemp(*a, **k)
        return staged["path"]

    monkeypatch.setattr(optional_deps.tempfile, "mkdtemp", _mk)
    result: list[bool] = []
    # No cancel_event of its own, like the Hardware wizard's or Advanced dialog's install.
    thread = threading.Thread(
        target=lambda: result.append(optional_deps.install("alignment", timeout=60)))
    thread.start()
    for _ in range(100):  # pip started: the staging directory exists
        if "path" in staged:
            break
        threading.Event().wait(0.05)

    optional_deps.request_stop_installs()

    assert optional_deps.wait_until_idle(15.0) is True
    thread.join(5)
    assert result == [False]
    assert not os.path.exists(staged["path"])


def test_the_exit_waits_for_a_merge_in_progress_and_nothing_is_half_done(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    final = _env(monkeypatch, tmp_path)
    monkeypatch.setattr(optional_deps.subprocess, "Popen",
                        lambda cmd, **_k: _FinishedProc(cmd[cmd.index("--target") + 1]))
    in_merge, release = threading.Event(), threading.Event()
    real_copytree = optional_deps.shutil.copytree

    def _slow_copytree(src: Any, dst: Any, *a: Any, **k: Any) -> Any:
        in_merge.set()
        release.wait(10)
        return real_copytree(src, dst, *a, **k)

    monkeypatch.setattr(optional_deps.shutil, "copytree", _slow_copytree)
    thread = threading.Thread(target=lambda: optional_deps.install("alignment", timeout=60))
    thread.start()
    assert in_merge.wait(10)

    optional_deps.request_stop_installs()  # the merge is not interruptible: it must finish
    assert optional_deps.installs_merging() is True
    assert optional_deps.wait_until_idle(0.3) is False  # still merging

    release.set()
    assert optional_deps.wait_until_idle(10.0) is True
    thread.join(5)
    assert (final / "bigpkg" / "__init__.py").exists()
    assert not [p for p in final.iterdir() if ".bak-" in p.name or ".merge-" in p.name]
    assert optional_deps.installs_merging() is False


def test_an_install_queued_behind_the_exit_request_does_not_start_pip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    _env(monkeypatch, tmp_path)
    started: list[int] = []
    monkeypatch.setattr(optional_deps.subprocess, "Popen",
                        lambda *a, **k: started.append(1) or _HangingProc())
    optional_deps.request_stop_installs()

    assert optional_deps.install("alignment", timeout=60) is False
    assert started == []


def test_the_counters_reset_when_an_install_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: Any, **_k: Any) -> bool:
        optional_deps._mark_merging()
        raise RuntimeError("boom")

    monkeypatch.setattr(optional_deps, "_install_impl", _boom)
    with pytest.raises(RuntimeError):
        optional_deps.install("alignment")

    assert optional_deps.wait_until_idle(0.0) is True
    assert optional_deps.installs_merging() is False


# ------------------------------------------------------------------- on_exit wiring


def _exit_fake(calls: list[str]) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _exit_from_tray=True, app_config={}, tray=None, queue=[], download_queue=[],
        _closing=False, _folder_watcher=None, history=None,
        withdraw=lambda: None, destroy=lambda: calls.append("destroy"),
        _save_window_geometry=lambda: None,
        _shutdown_server_on_exit=lambda: None,
        transcription_service=types.SimpleNamespace(
            stop_all=lambda **_k: calls.append("stop_all"),
            settle_done_on_exit=lambda: 0),
    )


def _patch_teardown(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: True)
    monkeypatch.setattr(app_module, "stop_live_session", lambda _a: None)
    monkeypatch.setattr(app_module, "stop_voice_clone_worker",
                        lambda _a: calls.append("voice"))


def test_on_exit_stops_installs_and_waits_before_the_workers_go(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_teardown(monkeypatch, calls)
    monkeypatch.setattr(optional_deps, "request_stop_installs", lambda: calls.append("stop"))
    monkeypatch.setattr(optional_deps, "wait_until_idle",
                        lambda t: calls.append(f"wait{t:g}") or True)

    App.on_exit(_exit_fake(calls))  # type: ignore[arg-type]

    assert calls == ["voice", "stop", f"wait{app_module.INSTALL_EXIT_WAIT_S:g}",
                     "stop_all", "destroy"]


def test_an_install_that_will_not_finish_does_not_block_the_exit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    calls: list[str] = []
    _patch_teardown(monkeypatch, calls)
    monkeypatch.setattr(optional_deps, "request_stop_installs", lambda: None)
    monkeypatch.setattr(optional_deps, "wait_until_idle", lambda t: False)
    monkeypatch.setattr(optional_deps, "installs_merging", lambda: True)

    App.on_exit(_exit_fake(calls))  # type: ignore[arg-type]

    assert calls[-1] == "destroy"
    assert "still running" in caplog.text


def test_a_declined_exit_leaves_installs_running(monkeypatch: pytest.MonkeyPatch) -> None:
    """'No' on the queued-tasks question must not cancel anything for the rest of the session."""
    calls: list[str] = []
    _patch_teardown(monkeypatch, calls)
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_a, **_k: False)
    fake = _exit_fake(calls)
    fake.queue = [types.SimpleNamespace(status="running", process=None, history_id=1)]

    App.on_exit(fake)  # type: ignore[arg-type]

    assert not optional_deps._stop_requested.is_set()
    assert calls == []


def test_cancelling_the_unsaved_transcript_question_leaves_installs_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    _patch_teardown(monkeypatch, calls)
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: False)  # Cancel
    fake = _exit_fake(calls)

    App.on_exit(fake)  # type: ignore[arg-type]

    assert not optional_deps._stop_requested.is_set()
    assert calls == []


# ------------------------------------------- the install caller after the window is gone


def test_an_install_that_ends_because_of_the_exit_does_not_touch_the_closed_app() -> None:
    import tkinter as tk

    def _dead(*_a: Any) -> None:
        raise tk.TclError("application has been destroyed")

    stopped: list[int] = []
    fake = types.SimpleNamespace(
        _closing=True, log=_dead,
        transcription_service=types.SimpleNamespace(stop_all=lambda: stopped.append(1)))

    assert App._finish_optional_install(fake, False, "Alignment") is False  # type: ignore[arg-type]
    assert App._finish_optional_install(fake, True, "Alignment") is True  # type: ignore[arg-type]
    assert stopped == []  # no worker restart while the app is closing


def test_a_normal_finished_install_still_logs_and_restarts_the_workers() -> None:
    logs: list[str] = []
    stopped: list[int] = []
    fake = types.SimpleNamespace(
        _closing=False, log=logs.append,
        transcription_service=types.SimpleNamespace(stop_all=lambda: stopped.append(1)))

    assert App._finish_optional_install(fake, True, "Alignment") is True  # type: ignore[arg-type]
    assert logs == ["Alignment installed."] and stopped == [1]
    assert App._finish_optional_install(fake, False, "Alignment") is False  # type: ignore[arg-type]


def test_a_tcl_error_while_logging_after_the_install_is_swallowed() -> None:
    import tkinter as tk

    def _dead(*_a: Any) -> None:
        raise tk.TclError("can't invoke text command")

    fake = types.SimpleNamespace(
        _closing=False, log=_dead,
        transcription_service=types.SimpleNamespace(stop_all=lambda: None))

    assert App._finish_optional_install(fake, True, "Alignment") is True  # type: ignore[arg-type]
