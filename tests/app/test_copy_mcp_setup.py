"""Help > Copy MCP setup: the copied ``claude mcp add`` command.

The command must carry the server's live port (the one it actually bound,
not only the one chosen on the Web / LAN tab) and must never carry the real
access password: that stays the ``<access password>`` placeholder for the
user to fill in.
"""
from __future__ import annotations

import sys
import tkinter as tk
import types

import pytest


@pytest.fixture
def App(monkeypatch):
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        # setitem: the stub must not outlive the test (later tests patch faster_whisper.utils)
        monkeypatch.setitem(sys.modules, "faster_whisper", fw)
    from app.app import App as _App
    return _App


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Handle:
    def __init__(self, port: int, *, running: bool = True,
                 https: bool = False) -> None:
        self.port = port
        self.https = https
        self._running = running

    def is_running(self) -> bool:
        return self._running


@pytest.fixture
def ui(App):
    root = tk.Tk()
    root.withdraw()
    # Let Tk create the window before the clipboard is used: on Tk 9 (Windows) a
    # clipboard call on a root that never processed its events crashed the process.
    root.update_idletasks()
    a = App.__new__(App)
    a.app_config = {"server_port": 8765}
    a.server_port_var = _Var(8765)
    a.server_https_enabled_var = _Var(False)
    a._server_handle = None
    a.logs = []
    a.log = a.logs.append
    a.clipboard_clear = root.clipboard_clear
    a.clipboard_append = root.clipboard_append
    yield a, root
    root.destroy()


def _expected(port: int, scheme: str = "http") -> str:
    return (f"claude mcp add --transport http whisper "
            f"{scheme}://127.0.0.1:{port}/mcp "
            '--header "Authorization: Bearer <access password>"')


def test_copies_the_bound_port_and_no_password(App, ui):
    a, root = ui
    a._server_handle = _Handle(8123)
    a._server_token_in_use = "s3cret"    # the real password: never copied
    App.copy_mcp_setup(a)
    got = root.clipboard_get()
    assert got == _expected(8123)
    assert "s3cret" not in got
    assert "<access password>" in got
    assert "MCP setup command copied" in a.logs[0]


def test_while_the_server_is_off_uses_the_chosen_port(App, ui):
    a, root = ui
    a.server_port_var = _Var(9001)
    App.copy_mcp_setup(a)
    assert root.clipboard_get() == _expected(9001)


def test_an_https_server_yields_an_https_url(App, ui):
    a, root = ui
    a._server_handle = _Handle(8443, https=True)
    App.copy_mcp_setup(a)
    assert root.clipboard_get() == _expected(8443, scheme="https")
