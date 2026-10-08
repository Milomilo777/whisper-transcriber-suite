"""The GUI and the web server hold the mutex that the installer's AppMutex names.

installer_embed.iss lists AppMutex; Setup and the uninstaller only notice a
running app (and ask to close it) when the app really creates that mutex.
"""
from __future__ import annotations

import re
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

import gui

_REPO = Path(__file__).resolve().parents[2]


def test_installer_names_the_mutex_the_app_creates():
    iss = (_REPO / "installer_embed.iss").read_text(encoding="utf-8")
    m = re.search(r"(?m)^AppMutex=(.+)$", iss)
    assert m, "installer_embed.iss has no AppMutex"
    names = [n.strip() for n in m.group(1).split(",")]
    assert names == [gui.APP_MUTEX_NAME, "Global\\" + gui.APP_MUTEX_NAME]


@pytest.mark.parametrize("argv", [["gui.py"], ["gui.py", "serve"]])
def test_gui_and_server_take_the_mutex_before_starting(monkeypatch, argv):
    calls: list[str] = []
    monkeypatch.setattr(gui, "_hold_app_mutex", lambda: calls.append("mutex"))
    monkeypatch.setattr(gui, "_cli_serve", lambda args: calls.append("serve") or 0)
    import app

    monkeypatch.setattr(app, "run", lambda *a: calls.append("run"))
    monkeypatch.setattr(sys, "argv", argv)
    assert gui.main() == 0
    assert calls == ["mutex", "serve" if "serve" in argv else "run"]


def test_worker_does_not_take_the_mutex(monkeypatch):
    calls: list[str] = []
    monkeypatch.setattr(gui, "_hold_app_mutex", lambda: calls.append("mutex"))
    import core.worker as worker

    monkeypatch.setattr(worker, "main", lambda: 0)
    monkeypatch.setattr(sys, "argv", ["gui.py", "--worker"])
    assert gui.main() == 0
    assert calls == []


@pytest.mark.skipif(sys.platform != "win32", reason="named mutexes are a Windows feature")
def test_mutex_exists_while_the_process_runs_and_goes_with_it():
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    synchronize = 0x00100000

    # A unique name: the real one may be held by a running app, or by this
    # test process after another test ran the real gui.main().
    name = f"WTS-test-{uuid.uuid4().hex}"

    def mutex_exists(prefix: str = "") -> bool:
        handle = kernel32.OpenMutexW(synchronize, False, prefix + name)
        if handle:
            kernel32.CloseHandle(handle)
        return bool(handle)

    assert not mutex_exists() and not mutex_exists("Global\\")
    code = ("import sys; sys.path.insert(0, sys.argv[1]); import gui; "
            "gui.APP_MUTEX_NAME = sys.argv[2]; gui._hold_app_mutex(); gui._hold_app_mutex(); "
            "print('held', flush=True); sys.stdin.read()")
    proc = subprocess.Popen([sys.executable, "-c", code, str(_REPO), name],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert proc.stdout is not None and proc.stdout.readline().strip() == "held"
        assert mutex_exists() and mutex_exists("Global\\")
    finally:
        assert proc.stdin is not None
        proc.stdin.close()
        proc.wait(timeout=30)
    assert not mutex_exists() and not mutex_exists("Global\\")
