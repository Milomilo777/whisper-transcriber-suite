"""``core.process_exit`` can start the app again after the process has ended (language restart)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from core import process_exit


@pytest.fixture(autouse=True)
def _clean() -> Any:
    process_exit.cancel_relaunch()
    yield
    process_exit.cancel_relaunch()


def test_command_is_the_interpreter_and_gui_script_on_windows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    script = tmp_path / "gui.py"
    script.write_text("", encoding="utf-8")
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", [str(script), "movie.mp4"])
    assert process_exit.relaunch_command() == [sys.executable, str(script)]  # no file argument kept


def test_command_of_a_frozen_build_is_the_exe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert process_exit.relaunch_command() == [sys.executable]


@pytest.mark.parametrize("platform", ["darwin", "linux"])
def test_other_platforms_are_not_supported(platform: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", platform)
    assert process_exit.relaunch_command() is None
    assert process_exit.request_relaunch() is False
    assert not process_exit.relaunch_requested()


def test_a_script_that_is_not_a_file_is_not_supported(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "argv", ["-c"])
    assert process_exit.relaunch_command() is None


def test_end_process_starts_the_command_after_the_flush_and_before_the_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    order: list[str] = []
    monkeypatch.setattr(process_exit, "_flush_everything", lambda: order.append("flush"))
    monkeypatch.setattr(process_exit, "_hard_exit", lambda code: order.append(f"exit{code}"))
    started: list[Any] = []
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: started.append((cmd, kw)) or order.append("spawn"))
    assert process_exit.request_relaunch([sys.executable, os.path.abspath(__file__)])
    process_exit.end_process(0)
    assert order == ["flush", "spawn", "exit0"]
    cmd, kw = started[0]
    # The replacement is told which process to wait for, so it cannot be rejected by a lock the
    # old process still holds (it starts before the hard exit).
    assert cmd == [sys.executable, os.path.abspath(__file__), "--wait-for-pid", str(os.getpid())]
    assert kw["stdin"] is subprocess.DEVNULL and kw["close_fds"] is True


def test_nothing_starts_without_a_request_or_after_a_cancel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(process_exit, "_flush_everything", lambda: None)
    monkeypatch.setattr(process_exit, "_hard_exit", lambda code: None)
    started: list[Any] = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: started.append(a))
    process_exit.end_process(0)
    process_exit.request_relaunch(["x", "y"])
    process_exit.cancel_relaunch()
    process_exit.end_process(0)
    assert started == []


def test_a_failed_start_still_ends_the_process(monkeypatch: pytest.MonkeyPatch) -> None:
    codes: list[int] = []
    monkeypatch.setattr(process_exit, "_flush_everything", lambda: None)
    monkeypatch.setattr(process_exit, "_hard_exit", codes.append)

    def boom(*_a: Any, **_k: Any) -> None:
        raise OSError("blocked")

    monkeypatch.setattr(subprocess, "Popen", boom)
    process_exit.request_relaunch(["x", "y"])
    process_exit.end_process(3)
    assert codes == [3]
    assert threading.current_thread() is threading.main_thread()


# --- the replacement waits for the old process ------------------------------------------------

def _clock() -> Any:
    now = [0.0]

    def tick() -> float:
        return now[0]

    def sleep(seconds: float) -> None:
        now[0] += seconds

    return tick, sleep


def test_the_replacement_waits_while_the_old_process_lives_and_goes_on_after() -> None:
    tick, sleep = _clock()
    lives = iter([True, True, True, False])
    seen: list[int] = []

    def alive(pid: int) -> bool:
        seen.append(pid)
        return next(lives)

    argv = ["gui.py", "--wait-for-pid", "4242", "movie one.mp4"]
    out = process_exit.consume_wait_for_pid(argv, alive=alive, sleep=sleep, clock=tick)
    assert out == ["gui.py", "movie one.mp4"]  # the option is gone; other arguments keep their form
    assert seen == [4242] * 4 and 0.25 < tick() < 0.5  # it polled until the process ended


def test_the_wait_is_bounded() -> None:
    tick, sleep = _clock()
    out = process_exit.consume_wait_for_pid(["gui.py", "--wait-for-pid", "7"], alive=lambda _p: True,
                                            sleep=sleep, clock=tick, timeout=2.0)
    assert out == ["gui.py"] and 2.0 <= tick() < 2.5


def test_no_option_means_no_wait_and_a_bad_pid_is_dropped() -> None:
    def never(_pid: int) -> bool:
        raise AssertionError("must not look at any process")

    argv = ["gui.py", "x.mp4"]
    assert process_exit.consume_wait_for_pid(argv, alive=never) is argv
    assert process_exit.consume_wait_for_pid(["gui.py", "--wait-for-pid", "abc"], alive=never) == ["gui.py", "abc"]
    assert process_exit.consume_wait_for_pid(["gui.py", "--wait-for-pid"], alive=never) == ["gui.py"]


def test_no_restart_loop_the_consumed_argv_never_carries_the_option() -> None:
    out = process_exit.consume_wait_for_pid(["gui.py", "--wait-for-pid", "1"], alive=lambda _p: False)
    assert process_exit.WAIT_FOR_PID_ARG not in out
    process_exit.request_relaunch([sys.executable, "gui.py"])
    assert process_exit._relaunch == [[sys.executable, "gui.py"]]  # the stored command stays clean


def test_a_real_process_is_waited_for() -> None:
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1.5)"])
    try:
        assert process_exit.pid_alive(child.pid) is True
        start = time.monotonic()
        process_exit.consume_wait_for_pid(["g", "--wait-for-pid", str(child.pid)], timeout=15)
        assert time.monotonic() - start > 0.5
        assert process_exit.pid_alive(child.pid) is False
    finally:
        child.wait(timeout=20)
    assert process_exit.pid_alive(child.pid) is False
    assert process_exit.pid_alive(0) is False


def test_gui_waits_before_the_tls_setup_the_mutex_or_any_config_use() -> None:
    import inspect

    import gui

    src = inspect.getsource(gui.main)
    wait_at = src.index("consume_wait_for_pid")
    for later in ("tls_trust.configure()", "_hold_app_mutex", "_activate_safe_mode", "load_config"):
        if later in src:
            assert wait_at < src.index(later), later
