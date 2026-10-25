"""``core.process_exit`` can start the app again after the process has ended (language restart)."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
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
    assert cmd == [sys.executable, os.path.abspath(__file__)]
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
