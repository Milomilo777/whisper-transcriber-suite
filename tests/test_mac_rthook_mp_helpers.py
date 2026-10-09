"""The macOS runtime hook runs only the exact multiprocessing helper commands.

``platform/macos/pyinstaller/rthook_mp_helpers.py`` diverts the
``-c "from multiprocessing.resource_tracker import main;main(6)"`` re-launch
of a frozen app. It must not turn into a way to run any code placed after
that prefix on the command line.
"""
from __future__ import annotations

import runpy
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "platform" / "macos" / "pyinstaller" / "rthook_mp_helpers.py"

# What CPython's multiprocessing builds for its helper processes.
GOOD = [
    "from multiprocessing.resource_tracker import main;main(6)",
    "from multiprocessing.forkserver import main; main(7, 8, ['__main__'], **{})",
    "from multiprocessing.forkserver import main; main(7, 8, [], "
    "**{'sys_path': ['/a/b', 'c d'], 'main_path': '/x/gui.py'})",
]
BAD = [
    "from multiprocessing.resource_tracker import main;main(6);import os",
    "from multiprocessing.resource_tracker import main;main(__import__('os').getpid())",
    "from multiprocessing.resource_tracker import main;main(6) or exit(3)",
    "from multiprocessing.resource_tracker import main;exit(6)",
    "from multiprocessing.resource_tracker import main;main",
    "from multiprocessing.resource_tracker import main as m;m(6)",
    "from multiprocessing.resource_tracker import main, os;main(6)",
    "from multiprocessing.os import main;main(6)",
    "from multiprocessing.resource_tracker import main;main(*sys.argv)",
    "from multiprocessing.resource_tracker import main;main(**open('x'))",
    "from multiprocessing.resource_tracker import main\nmain(6)\nmain(7)",
    "from multiprocessing.resource_tracker import main;main(",
    "from multiprocessing.resource_tracker import main;main(6)\x00",
    "import os;from multiprocessing.resource_tracker import main;main(6)",
    "",
]


def _load_hook():
    saved = sys.argv
    sys.argv = ["app"]
    try:
        return runpy.run_path(str(HOOK))
    finally:
        sys.argv = saved


@pytest.mark.parametrize("command", GOOD)
def test_the_helper_commands_multiprocessing_builds_are_accepted(command):
    code = _load_hook()["_wts_helper_code"](command)
    assert code is not None


@pytest.mark.parametrize("command", BAD)
def test_anything_else_is_refused(command):
    assert _load_hook()["_wts_helper_code"](command) is None


def test_extra_code_after_the_prefix_is_not_executed(tmp_path):
    marker = tmp_path / "ran"
    command = (
        "from multiprocessing.resource_tracker import main;"
        f"open({str(marker)!r}, 'w').close()"
    )
    runner = (
        "import runpy, sys\n"
        "hook, command = sys.argv[1:3]\n"
        "sys.argv = ['app', '-c', command]\n"
        "runpy.run_path(hook)\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", runner, str(HOOK), command],
        capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL,
    )
    assert result.returncode == 0, result.stderr
    assert not marker.exists()
