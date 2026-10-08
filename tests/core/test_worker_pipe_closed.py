"""The worker's output pipe closing (the app quit) is one quiet line, not a traceback."""
from __future__ import annotations

import errno
import logging
from typing import Any

import pytest

from core import worker
from core.task import TranscriptionTask
from core.transcriber import _with_task_prefix

_REAL_QUIET_STDOUT = worker._quiet_stdout_for_exit


@pytest.fixture(autouse=True)
def _clean_session(monkeypatch: pytest.MonkeyPatch) -> Any:
    # Never let a test repoint the runner's own fd 1 (pytest -s).
    monkeypatch.setattr(worker, "_quiet_stdout_for_exit", lambda: None)
    worker._end_session()
    yield
    worker._end_session()


def _broken_print(monkeypatch: pytest.MonkeyPatch, exc: BaseException) -> None:
    def _print(*_a: Any, **_k: Any) -> None:
        raise exc

    monkeypatch.setattr(worker, "print", _print, raising=False)


def test_emit_survives_a_broken_pipe_and_checks_whether_the_app_is_gone(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    checks: list[str] = []
    monkeypatch.setattr(worker, "_on_pipe_closed", checks.append)
    _broken_print(monkeypatch, BrokenPipeError(32, "Broken pipe"))
    with caplog.at_level(logging.DEBUG, logger="core.worker"):
        worker.emit("log", message="a")
        worker.emit("progress", percent=1.0)
        worker.emit("log", message="b")

    assert checks == ["its output pipe is closed"]  # once, however many events follow
    lines = [r for r in caplog.records if r.name == "core.worker"
             and r.levelno >= logging.WARNING]
    assert len(lines) == 1 and lines[0].exc_info is None


def test_a_log_line_after_the_app_quit_leaves_no_traceback(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    """The reported case: transcriber's log wrapper used to log a BrokenPipeError traceback."""
    monkeypatch.setattr(worker, "_on_pipe_closed", lambda _r: None)
    _broken_print(monkeypatch, BrokenPipeError(32, "Broken pipe"))
    wrapped = _with_task_prefix(lambda m: worker.emit("log", message=m),
                                TranscriptionTask("sample_clip.mp3"))
    assert wrapped is not None
    with caplog.at_level(logging.DEBUG):
        wrapped("Task cancelled")
    assert not [r for r in caplog.records if r.exc_info]
    assert not [r for r in caplog.records if "log callback raised" in r.getMessage()]


def test_a_second_session_reports_the_closed_pipe_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks: list[str] = []
    monkeypatch.setattr(worker, "_on_pipe_closed", checks.append)
    _broken_print(monkeypatch, BrokenPipeError(32, "Broken pipe"))
    worker.emit("log", message="a")
    worker._begin_session()
    worker.emit("log", message="b")
    assert len(checks) == 2


@pytest.mark.parametrize("exc", [PermissionError(13, "denied"), OSError(28, "No space left")])
def test_other_write_errors_are_not_hidden(
    monkeypatch: pytest.MonkeyPatch, exc: OSError,
) -> None:
    monkeypatch.setattr(worker, "_on_pipe_closed", lambda _r: pytest.fail("not a pipe"))
    _broken_print(monkeypatch, exc)
    with pytest.raises(type(exc)):
        worker.emit("log", message="a")


def test_the_heartbeat_path_still_notices_a_closed_pipe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The heartbeat relied on emit() raising; emit() now reports the closed pipe itself."""
    checks: list[str] = []
    monkeypatch.setattr(worker, "_on_pipe_closed", checks.append)
    _broken_print(monkeypatch, BrokenPipeError(32, "Broken pipe"))
    worker.emit("heartbeat", ts=1.0)
    assert checks == ["its output pipe is closed"]


class _FakeStdout:
    def __init__(self, fd: int) -> None:
        self._fd = fd

    def fileno(self) -> int:
        if self._fd < 0:
            raise OSError("no fileno")
        return self._fd


def test_stdout_is_pointed_at_the_null_device_only_when_it_is_the_process_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import os
    import sys

    real = _REAL_QUIET_STDOUT
    dup: list[tuple[int, int]] = []
    monkeypatch.setattr(os, "dup2", lambda src, dst: dup.append((src, dst)))

    monkeypatch.setattr(sys, "stdout", _FakeStdout(7))  # a captured stream
    real()
    monkeypatch.setattr(sys, "stdout", _FakeStdout(-1))  # no file descriptor
    real()
    assert dup == []

    monkeypatch.setattr(sys, "stdout", _FakeStdout(1))
    real()
    assert len(dup) == 1 and dup[0][1] == 1


# ---------------------------------------------- Windows reports a closed pipe as EINVAL


@pytest.mark.parametrize("err", [errno.EINVAL, errno.EPIPE])
def test_a_plain_oserror_on_the_process_stdout_counts_as_the_app_leaving(
    monkeypatch: pytest.MonkeyPatch, err: int,
) -> None:
    """Windows: writing to a pipe the app closed raises OSError(22, 'Invalid argument')."""
    import sys

    checks: list[str] = []
    monkeypatch.setattr(worker, "_on_pipe_closed", checks.append)
    monkeypatch.setattr(sys, "stdout", _FakeStdout(1))
    _broken_print(monkeypatch, OSError(err, "pipe closed"))

    worker.emit("log", message="a")
    worker.emit("log", message="b")

    assert checks == ["its output pipe is closed"]


@pytest.mark.parametrize("fd", [7, -1])
def test_the_same_errno_from_another_stream_is_a_real_error(
    monkeypatch: pytest.MonkeyPatch, fd: int,
) -> None:
    import sys

    monkeypatch.setattr(worker, "_on_pipe_closed", lambda _r: pytest.fail("not the app pipe"))
    monkeypatch.setattr(sys, "stdout", _FakeStdout(fd))  # a captured stream / no descriptor
    _broken_print(monkeypatch, OSError(errno.EINVAL, "Invalid argument"))

    with pytest.raises(OSError):
        worker.emit("log", message="a")


@pytest.mark.parametrize("err", [errno.ENOSPC, errno.EBADF, errno.EACCES])
def test_other_errnos_on_the_process_stdout_still_raise(
    monkeypatch: pytest.MonkeyPatch, err: int,
) -> None:
    import sys

    monkeypatch.setattr(worker, "_on_pipe_closed", lambda _r: pytest.fail("not a closed pipe"))
    monkeypatch.setattr(sys, "stdout", _FakeStdout(1))
    _broken_print(monkeypatch, OSError(err, "other"))

    with pytest.raises(OSError):
        worker.emit("log", message="a")


_CHILD = """
import sys, time
sys.path.insert(0, sys.argv[1])
from core import worker
marker = sys.argv[2]
time.sleep(1.5)          # the parent closes its read end meanwhile
worker.emit("log", message="after the app left")
worker.emit("log", message="and again")
open(marker, "w").write("survived")
"""


def test_a_real_closed_pipe_does_not_crash_the_worker_process(tmp_path: Any) -> None:
    """The OS-specific error (EINVAL on Windows, EPIPE elsewhere) is absorbed for real."""
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[2]
    marker = tmp_path / "marker.txt"
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(repo), str(marker)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
    )
    assert proc.stdout is not None
    proc.stdout.close()  # the app quit: nobody reads the worker's stdout any more
    assert proc.stderr is not None
    err = proc.stderr.read()
    proc.wait(timeout=60)

    assert marker.exists(), err.decode("utf-8", "replace")
    assert b"Traceback" not in err
    assert b"Exception ignored" not in err  # nor a complaint at interpreter exit
