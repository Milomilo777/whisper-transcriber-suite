"""Closing the window ends the process even while a library thread pool still runs.

huggingface_hub downloads a model on an 8-thread ``ThreadPoolExecutor`` that cannot be
interrupted; Python waits for those threads at interpreter exit, so the window-less app
lived on (holding the Windows ``AppMutex``) until the whole model had arrived.
``gui.py`` now ends the process after ``app.run()`` returns, via ``core.process_exit``.

The end-to-end tests run ``gui._script_main`` (what ``python gui.py`` executes) in a
child interpreter with a fake ``app.run`` whose "download" outlives the window.
"""
from __future__ import annotations

import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from core import process_exit

_REPO = Path(__file__).resolve().parents[2]

_CHILD = textwrap.dedent(
    """
    import logging, sys, threading, time
    from concurrent.futures import ThreadPoolExecutor
    sys.path.insert(0, sys.argv[1])
    mode, log_path = sys.argv[2], sys.argv[3]
    import gui, app

    logging.basicConfig(filename=log_path, level=logging.INFO, encoding="utf-8")

    def fake_run(*_a, **_k):
        if mode == "crash":
            raise RuntimeError("window could not be built")
        if mode == "download":
            def download_like():
                with ThreadPoolExecutor(max_workers=4) as ex:
                    list(ex.map(lambda i: time.sleep(6), range(8)))  # 2 rounds x 6 s
            threading.Thread(target=download_like, daemon=True).start()
            time.sleep(0.4)
        print("stdout-marker")  # block-buffered on a pipe: only a flush gets it out
        logging.getLogger("t").info("log-marker")

    app.run = fake_run
    gui._hold_app_mutex = lambda: None
    sys.argv = ["gui.py"]
    sys.excepthook = lambda t, e, tb: print("excepthook-called", t.__name__, flush=True)
    gui._script_main()
    """
)


def _run_child(tmp_path: Path, mode: str) -> tuple[subprocess.CompletedProcess[str], float, str]:
    script = tmp_path / "child.py"
    script.write_text(_CHILD, encoding="utf-8")
    log = tmp_path / "child.log"
    started = time.monotonic()
    proc = subprocess.run(
        [sys.executable, str(script), str(_REPO), mode, str(log)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    elapsed = time.monotonic() - started
    return proc, elapsed, log.read_text(encoding="utf-8") if log.exists() else ""


def test_a_running_download_pool_does_not_keep_the_process_alive(tmp_path: Path) -> None:
    proc, elapsed, log = _run_child(tmp_path, "download")

    assert proc.returncode == 0, proc.stderr
    # Without the exit the interpreter joined the pool: 12 s. Interpreter start-up
    # and imports stay far below the margin.
    assert elapsed < 8.0, f"the process lingered for {elapsed:.1f} s after the window closed"
    assert "stdout-marker" in proc.stdout  # buffered output was flushed first
    assert "log-marker" in log  # and so were the logs


def test_a_normal_exit_without_stragglers_is_also_clean(tmp_path: Path) -> None:
    proc, _elapsed, log = _run_child(tmp_path, "plain")

    assert proc.returncode == 0, proc.stderr
    assert "stdout-marker" in proc.stdout
    assert "log-marker" in log


def test_a_crash_still_reaches_the_excepthook_and_is_not_swallowed(tmp_path: Path) -> None:
    proc, _elapsed, _log = _run_child(tmp_path, "crash")

    assert "excepthook-called RuntimeError" in proc.stdout  # app.crash_report's hook runs
    assert proc.returncode == 1


# ------------------------------------------------------------- end_process units


def test_end_process_flushes_the_logs_and_streams_before_the_hard_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    monkeypatch.setattr(process_exit.logging, "shutdown", lambda: order.append("logging"))
    monkeypatch.setattr(process_exit, "_flush_streams", lambda: order.append("streams"))
    monkeypatch.setattr(process_exit, "_hard_exit", lambda code: order.append(f"exit{code}"))

    process_exit.end_process(3)

    assert order == ["logging", "streams", "exit3"]


def test_end_process_still_exits_when_flushing_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    exits: list[int] = []

    def _boom() -> None:
        raise OSError("log disk gone")

    monkeypatch.setattr(process_exit.logging, "shutdown", _boom)
    monkeypatch.setattr(process_exit, "_hard_exit", exits.append)

    process_exit.end_process(0)

    assert exits == [0]


@pytest.mark.parametrize("stream", [None, "closed", "broken"])
def test_flush_streams_survives_unusable_standard_streams(
    monkeypatch: pytest.MonkeyPatch, stream: Any
) -> None:
    class _Broken:
        def flush(self) -> None:
            raise BrokenPipeError("pipe closed")  # an OSError

    class _Closed:
        def flush(self) -> None:
            raise ValueError("I/O operation on closed file")

    fake = {None: None, "closed": _Closed(), "broken": _Broken()}[stream]
    for name in ("stdout", "stderr", "__stdout__", "__stderr__"):
        monkeypatch.setattr(sys, name, fake)

    process_exit._flush_streams()  # must not raise


def test_blocking_threads_lists_only_live_non_daemon_threads() -> None:
    import threading

    release = threading.Event()
    keep = threading.Thread(target=release.wait, name="needs-a-join", daemon=False)
    quiet = threading.Thread(target=release.wait, name="daemon-one", daemon=True)
    keep.start()
    quiet.start()
    try:
        names = process_exit._blocking_threads()
        assert "needs-a-join" in names
        assert "daemon-one" not in names
    finally:
        release.set()
        keep.join()
        quiet.join()
