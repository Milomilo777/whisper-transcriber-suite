"""Quiet notices on macOS: a new notice is placed again once shown so Tk/aqua paints it."""
import tkinter as tk

import pytest

from app.widgets import notice


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.withdraw()
    yield r
    r.destroy()


def test_a_new_notice_is_placed_again_on_macos(root, monkeypatch):
    monkeypatch.setattr(notice.sys, "platform", "darwin")
    top = tk.Toplevel(root)
    host = notice.NoticeHost(top)
    places: list[str] = []
    real_place = host.frame.place

    def spy(*args, **kwargs):
        places.append("place")
        return real_place(*args, **kwargs)

    monkeypatch.setattr(host.frame, "place", spy)
    host.post("Saved")
    assert places == ["place"] and host._repaint_id is not None
    host._repaint()
    assert places == ["place", "place"]
    assert host._repaint_id is None
    top.destroy()


def test_other_systems_place_a_notice_once(root, monkeypatch):
    monkeypatch.setattr(notice.sys, "platform", "win32")
    top = tk.Toplevel(root)
    host = notice.NoticeHost(top)
    host.post("Saved")
    assert host._repaint_id is None
    top.destroy()


def test_destroying_the_window_cancels_a_pending_repaint(root, monkeypatch):
    monkeypatch.setattr(notice.sys, "platform", "darwin")
    top = tk.Toplevel(root)
    host = notice.NoticeHost(top)
    host.post("Saved")
    pending = host._repaint_id
    assert pending is not None
    top.destroy()
    assert host._repaint_id is None
    assert pending not in root.tk.call("after", "info")


def test_a_dismissed_notice_is_not_placed_back(root, monkeypatch):
    monkeypatch.setattr(notice.sys, "platform", "darwin")
    top = tk.Toplevel(root)
    host = notice.NoticeHost(top)
    host.post("Saved")
    host.dismiss()
    host._repaint()
    assert not host.frame.winfo_manager()
    top.destroy()
