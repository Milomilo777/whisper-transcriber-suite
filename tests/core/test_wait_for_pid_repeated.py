"""Repeated ``--wait-for-pid`` options must all be consumed.

``consume_wait_for_pid`` documents that it returns argv "without the option, so
nothing later sees it and a restart never repeats it". With more than one
occurrence on the command line (a stale flag copied twice into a shortcut, or a
relaunch chain that appended it twice) only the first was stripped and the
option leaked back into the program's argv.
"""
from __future__ import annotations

from core import process_exit


def test_repeated_wait_for_pid_all_stripped() -> None:
    never = lambda _pid: False  # noqa: E731 - nobody waits, every pid is already gone
    out = process_exit.consume_wait_for_pid(
        ["gui.py", "--wait-for-pid", "1", "--wait-for-pid", "2"],
        alive=never,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
    )
    assert out == ["gui.py"]


def test_repeated_wait_for_pid_malformed_then_valid() -> None:
    never = lambda _pid: False  # noqa: E731
    out = process_exit.consume_wait_for_pid(
        ["gui.py", "--wait-for-pid", "abc", "--wait-for-pid", "3"],
        alive=never,
        sleep=lambda _s: None,
        clock=lambda: 0.0,
    )
    # A malformed pid is not an option value: it stays as a plain argument
    # (single-occurrence behaviour), but the option itself must be gone.
    assert out == ["gui.py", "abc"]
