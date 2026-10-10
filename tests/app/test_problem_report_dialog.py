"""The Report a problem window: modal grab hand-over from About, system line, send states."""
import platform
import tkinter as tk
from unittest import mock

import pytest

from app.dialogs import problem_report as dialog
from core import problem_report as pr


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield r
    r.destroy()


def test_the_report_window_takes_the_about_grab_and_gives_it_back(root):
    about = tk.Toplevel(root)
    about.wait_visibility()
    about.grab_set()
    assert root.grab_current() is about
    win = dialog.open_problem_report(about, {"stats_url": ""}, "https://example.invalid/issues/new")
    root.update()
    # On macOS a child of a grabbing window got no clicks: the report window must hold the grab.
    assert root.grab_current() is win
    win.destroy()
    root.update()
    assert root.grab_current() is about
    about.destroy()


def test_send_is_disabled_until_there_is_text(root):
    win = dialog.open_problem_report(root, {"stats_url": ""}, "https://example.invalid/issues/new")
    root.update()
    buttons = {w.cget("text"): w for w in _walk(win) if w.winfo_class() == "TButton"}
    assert buttons["Send"].instate(["disabled"])
    text = next(w for w in _walk(win) if isinstance(w, tk.Text))
    text.insert("1.0", "It froze")
    text.event_generate("<KeyRelease>")
    root.update()
    assert not buttons["Send"].instate(["disabled"])
    win.destroy()


def test_the_system_line_names_macos_not_darwin():
    with mock.patch.object(platform, "system", return_value="Darwin"), \
            mock.patch.object(platform, "mac_ver", return_value=("10.15.7", ("", "", ""), "x86_64")):
        assert pr.os_name() == "macOS 10.15.7"
        assert "Darwin" not in pr.system_summary()
        assert pr.build_payload("x")["platform_release"] == "macOS 10.15.7"


def _walk(w):
    yield w
    for c in w.winfo_children():
        yield from _walk(c)
