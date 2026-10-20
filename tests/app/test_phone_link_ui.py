"""Web / LAN access tab: the phone QR code shows only while the page is shared on the network."""
from __future__ import annotations

import sys
import tkinter as tk
import types
from tkinter import ttk

import pytest


@pytest.fixture
def App():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    from app.app import App as _App
    return _App


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Btn:
    def config(self, **kw):
        pass


@pytest.fixture
def ui(App):
    root = tk.Tk()
    root.withdraw()
    a = App.__new__(App)
    a.app_config = {"server_port": 8765}
    a.server_port_var = _Var(8765)
    a.server_toggle_btn = _Btn()
    a.server_open_btn = _Btn()
    a.server_status_var = _Var("")
    a.server_url_var = _Var("")
    a._server_busy = True
    a.logs = []
    a.log = a.logs.append
    a.server_url_label = ttk.Label(root)
    a.server_url_label.pack()
    a.server_qr_frame = ttk.Frame(root)
    a.server_qr_label = ttk.Label(a.server_qr_frame)
    a.server_qr_label.pack()
    a.server_qr_note_var = tk.StringVar(root, value="")
    a.clipboard_clear = root.clipboard_clear
    a.clipboard_append = root.clipboard_append
    yield a, root
    root.destroy()


LAN = ["http://127.0.0.1:8765/", "http://192.168.1.5:8765/"]


def test_qr_shows_while_shared_and_hides_when_stopped(App, ui):
    pytest.importorskip("segno")
    a, root = ui
    a._server_token_in_use = ""
    App._on_server_started(a, LAN, 8765, True)
    assert a.server_qr_frame.winfo_manager() == "pack"
    assert str(a.server_qr_label.cget("image"))
    assert a._phone_qr_image.width() > 50
    assert a._phone_link == "http://192.168.1.5:8765/"
    assert "password" not in a.server_qr_note_var.get()
    App._on_server_stopped(a)
    assert a.server_qr_frame.winfo_manager() == ""
    assert a._phone_link == ""


@pytest.mark.parametrize("urls,share", [(LAN[:1], False), (LAN[:1], True)])
def test_no_qr_without_a_network_address(App, ui, urls, share):
    a, _root = ui
    App._on_server_started(a, urls, 8765, share)
    assert a.server_qr_frame.winfo_manager() == ""


def test_link_carries_the_password_in_use_and_copies(App, ui):
    a, root = ui
    a._server_token_in_use = "s3cret"
    App._on_server_started(a, LAN, 8765, True)
    assert a._phone_link == "http://192.168.1.5:8765/?token=s3cret"
    assert "password" in a.server_qr_note_var.get()
    App.copy_phone_link(a)
    assert root.clipboard_get() == "http://192.168.1.5:8765/?token=s3cret"


def test_link_keeps_the_password_the_server_started_with(App, ui):
    a, _root = ui
    a._server_token_in_use = "old"
    a.server_token_var = _Var("typed later")
    App._on_server_started(a, LAN, 8765, True)
    assert a._phone_link.endswith("?token=old")


def test_qr_draws_exactly_the_copied_link(App, ui, monkeypatch):
    a, _root = ui
    drawn = []
    monkeypatch.setattr("core.phone_link.qr_png_base64", lambda text, **_k: drawn.append(text) or "")
    a._server_token_in_use = "p&w"
    App._on_server_started(a, ["https://127.0.0.1:8765/", "https://192.168.1.5:8765/"], 8765, True)
    assert drawn == [a._phone_link] == ["https://192.168.1.5:8765/?token=p%26w"]
    assert "certificate" in a.server_qr_note_var.get()
    assert a.server_qr_frame.winfo_manager() == "pack"


def test_a_failed_start_hides_the_qr(App, ui, monkeypatch):
    a, _root = ui
    App._on_server_started(a, LAN, 8765, True)
    monkeypatch.setattr("app.app.messagebox.showerror", lambda *a, **k: None)
    App._on_server_failed(a, "Port 8765 is in use.")
    assert a.server_qr_frame.winfo_manager() == ""
