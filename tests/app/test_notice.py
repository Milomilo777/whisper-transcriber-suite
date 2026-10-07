"""Quiet notices (app/widgets/notice.py) and the call sites converted from message boxes.

The widget runs on a real Tk root; time is shortened by patching the duration constants and the
event loop is pumped by hand. Each converted call site is checked twice: a notice appears, and
no message box does (every messagebox function raises while the test runs).
"""
from __future__ import annotations

import json
import time
import tkinter as tk
from tkinter import messagebox, ttk
from types import SimpleNamespace

import pytest

from app.widgets import notice as notice_mod
from app.widgets.notice import MAX_QUEUE, NoticeHost, duration_ms, host_for, notify

_BOX_FUNCTIONS = (
    "showinfo", "showwarning", "showerror", "askyesno", "askokcancel", "askquestion",
    "askretrycancel", "askyesnocancel",
)


@pytest.fixture
def no_boxes(monkeypatch):
    """Every message box raises: a converted call site must not reach one."""
    def _boom(*args, **kwargs):
        raise AssertionError(f"a message box was opened: {args[:2]}")

    for name in _BOX_FUNCTIONS:
        monkeypatch.setattr(messagebox, name, _boom)


@pytest.fixture
def fast(monkeypatch):
    monkeypatch.setattr(notice_mod, "BASE_MS", 150)
    monkeypatch.setattr(notice_mod, "PER_CHAR_MS", 0)
    monkeypatch.setattr(notice_mod, "LEAVE_GRACE_MS", 60)


@pytest.fixture
def root():
    window = tk.Tk()
    window.geometry("400x300")
    window.update()
    try:
        yield window
    finally:
        window.destroy()


def _pump(window: tk.Misc, ms: int) -> None:
    end = time.monotonic() + ms / 1000
    while time.monotonic() < end:
        window.update()
        time.sleep(0.005)


# ---------------------------------------------------------------- the widget

def test_a_notice_shows_at_the_bottom_edge_and_hides_by_itself(root, fast):
    notify(root, "Saved 3 segments")
    host = host_for(root)
    assert host.visible
    assert host._text.get() == "Saved 3 segments"
    root.update()
    info = host.frame.place_info()
    assert float(info["rely"]) == 1.0 and info["anchor"] == "sw"
    _pump(root, 500)
    assert not host.visible
    assert not host.frame.winfo_manager()


def test_duration_grows_with_the_text_and_is_capped():
    assert duration_ms("ok") < duration_ms("x" * 80) <= notice_mod.MAX_MS
    assert duration_ms("x" * 10_000) == notice_mod.MAX_MS


def test_a_notice_stays_while_the_pointer_is_over_it(root, fast):
    notify(root, "Copied")
    host = host_for(root)
    host._on_enter()
    _pump(root, 450)
    assert host.visible  # well past its time, but hovered
    host._on_leave()
    _pump(root, 300)
    assert not host.visible


def test_a_notice_that_expired_while_hovered_hides_when_the_pointer_leaves(root, fast):
    notify(root, "Copied")
    host = host_for(root)
    # the timer is already running when the pointer arrives late
    host._hovered = True
    _pump(root, 450)
    assert host.visible  # the timer ran out while hovered, the notice waits
    host._on_leave()
    assert not host.visible


def test_the_queue_holds_at_most_three_and_drops_the_oldest_waiting(root, fast):
    for n in range(1, 6):
        notify(root, f"message {n}")
    host = host_for(root)
    assert host.queued == MAX_QUEUE == 3
    assert host.current is not None and host.current[0] == "message 1"
    assert [t for t, _k in host.pending] == ["message 4", "message 5"]
    seen = [host.current[0]]
    for _ in range(5):
        host.dismiss()
        if host.current:
            seen.append(host.current[0])
    assert seen == ["message 1", "message 4", "message 5"]
    assert not host.visible


def test_the_same_message_twice_is_one_notice(root, fast):
    notify(root, "Saved")
    notify(root, "Saved")
    host = host_for(root)
    assert host.queued == 1


def test_whitespace_is_folded_and_empty_text_is_ignored(root, fast):
    notify(root, "  line one\n  line two  ")
    notify(root, "   \n ")
    host = host_for(root)
    assert host._text.get() == "line one line two"
    assert host.queued == 1


def test_the_next_notice_follows_when_one_hides(root, fast):
    notify(root, "first")
    notify(root, "second", "warning")
    host = host_for(root)
    _pump(root, 220)
    assert host._text.get() == "second" and host.current == ("second", "warning")
    _pump(root, 400)
    assert not host.visible


def test_dismiss_key_closes_the_notice_and_otherwise_passes_through(root, fast):
    host = host_for(root)
    assert host._on_dismiss_key() is None  # nothing on screen: the key is not swallowed
    notify(root, "Saved")
    assert host._on_dismiss_key() == "break"
    assert not host.visible
    assert any("period" in seq for seq in root.bind())


def test_the_close_button_and_its_escape_key_dismiss(root, fast):
    notify(root, "one")
    host = host_for(root)
    host.close_button.invoke()
    assert not host.visible
    notify(root, "two")
    assert host._on_escape() == "break"
    assert not host.visible


def test_a_notice_never_takes_the_focus_or_a_grab(root, fast):
    entry = ttk.Entry(root)
    entry.pack()
    root.update()
    entry.focus_force()
    root.update()
    before = root.focus_get()
    notify(root, "Saved")
    root.update()
    assert root.focus_get() is before
    assert root.grab_current() is None


def test_each_window_has_its_own_host(root, fast):
    other = tk.Toplevel(root)
    try:
        child = ttk.Label(other, text="x")
        child.pack()
        notify(child, "in the second window")
        assert host_for(other).visible
        assert not getattr(root, notice_mod._HOST_ATTR, None)
        assert host_for(child) is host_for(other)
    finally:
        other.destroy()


def test_a_closing_window_loses_the_notice_without_an_error(root, fast, caplog):
    window = tk.Toplevel(root)
    label = ttk.Label(window)
    window.destroy()
    with caplog.at_level("INFO"):
        notify(label, "too late")
    assert "too late" in caplog.text


def test_closing_a_window_cancels_its_notice_timer(root, fast):
    # Tk deletes a destroyed window's Tcl commands but not its after() events: a timer left
    # pending would later fire into a deleted command ("invalid command name") as a
    # background error, which Tk reports with an error dialog while the app still runs.
    window = tk.Toplevel(root)
    notify(window, "about to close")
    timer = host_for(window)._after_id
    assert timer in root.tk.splitlist(root.tk.call("after", "info"))
    window.destroy()
    assert timer not in root.tk.splitlist(root.tk.call("after", "info"))


def test_unknown_kind_falls_back_to_info(root, fast):
    notify(root, "x", "nonsense")  # type: ignore[arg-type]
    assert host_for(root).current == ("x", "info")


def test_host_type(root):
    assert isinstance(host_for(root), NoticeHost)


# --------------------------------------------------- converted update-check calls

def test_manual_update_check_results_are_notices(no_boxes, monkeypatch):
    import app.app as app_mod
    from app.app import App
    from core import updates as u

    class _Host(tk.Tk):
        pass

    _Host._on_update_result = App._on_update_result  # type: ignore[attr-defined]
    window = _Host()
    window.withdraw()
    window._closing = False  # type: ignore[attr-defined]
    monkeypatch.setattr(app_mod, "_APP_VERSION", "1.9.3")
    try:
        info = u.UpdateInfo(
            latest_tag="v1.9.3", html_url="https://example.invalid/r", is_newer=False,
            headline="", highlights=(), assets=(),
        )
        window._on_update_result(info, manual=True)  # type: ignore[attr-defined]
        host = host_for(window)
        assert host.current is not None and host.current[1] == "success"
        assert "latest version (1.9.3)" in host.current[0]
        window._on_update_result(None, manual=True)  # type: ignore[attr-defined]
        assert [k for _t, k in host.pending] == ["warning"]
        assert "Could not reach the update server" in host.pending[0][0]
    finally:
        window.destroy()


def test_statistics_without_history_is_a_notice(no_boxes, root):
    from app.dialogs.statistics import show_statistics

    show_statistics(SimpleNamespace(history=None, winfo_toplevel=root.winfo_toplevel))  # type: ignore[arg-type]
    current = host_for(root).current
    assert current is not None and current[1] == "warning"
    assert "history.db" in current[0]


# ------------------------------------------------------- converted viewer calls

@pytest.fixture
def viewer(tmp_path, no_boxes, root):
    from app.dialogs.transcript_viewer import TranscriptViewer

    segs = [
        {"start": 0.0, "end": 1.0, "text": "um hello", "speaker": "Speaker 00"},
        {"start": 1.0, "end": 2.0, "text": "world", "speaker": "Speaker 01"},
    ]
    path = tmp_path / "v.json"
    path.write_text(json.dumps(segs), encoding="utf-8")
    window = TranscriptViewer(root, str(path))
    window.withdraw()
    try:
        yield window
    finally:
        window._dirty = False
        window.destroy()


def _last_notice(window: tk.Misc) -> tuple[str, str]:
    host = host_for(window)
    assert host.current is not None
    items = [host.current, *host.pending]
    return items[-1]


def test_viewer_saved_is_a_success_notice(viewer):
    viewer._dirty = True
    viewer._save_changes()
    text, kind = _last_notice(viewer)
    assert kind == "success" and text.startswith("Saved 2 segment(s)")
    assert viewer._dirty is False


def test_viewer_rename_is_a_notice(viewer, monkeypatch):
    from app.dialogs import transcript_viewer as tv

    monkeypatch.setattr(tv.simpledialog, "askstring", lambda *a, **k: "Alice")
    viewer._rename_speaker("Speaker 00")
    text, kind = _last_notice(viewer)
    assert kind == "success" and text.startswith("Renamed 1 segment(s)")


def test_viewer_remove_fillers_is_a_notice_after_its_question(viewer, monkeypatch):
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    viewer._remove_fillers()
    text, _kind = _last_notice(viewer)
    assert text.startswith("Fillers removed: updated ")


def test_viewer_hints_are_notices(viewer):
    viewer._ai_question_var.set("")
    viewer._run_ask()
    assert _last_notice(viewer) == ("Type a question first.", "warning")
    viewer.media_path = None
    viewer._open_in_system_player()
    assert "No media file" in _last_notice(viewer)[0]
    viewer.segments = []
    viewer._run_bilingual_translate()
    assert "no segments to translate" in _last_notice(viewer)[0]


def test_viewer_ai_off_hint_is_a_notice(viewer, monkeypatch):
    monkeypatch.setattr(type(viewer), "_app_config", lambda self: {"ai_enabled": False})
    viewer._run_ai_task("Ask", lambda runner: "x")
    assert "AI Layer is off" in _last_notice(viewer)[0]
    viewer._run_bilingual_translate()
    assert "AI Layer is off" in _last_notice(viewer)[0]


# ------------------------------------------------ review findings (regression tests)

def test_pointer_on_a_sibling_whose_path_starts_like_the_notice_is_outside(root, fast, monkeypatch):
    notify(root, "Copied")
    host = host_for(root)
    late = ttk.Frame(root)  # made after the host, so its path extends the frame's path
    assert str(late).startswith(str(host.frame))
    host._on_enter()
    monkeypatch.setattr(host.frame, "winfo_containing", lambda x, y: late)
    host._on_leave()
    assert not host._hovered
    _pump(root, 500)
    assert not host.visible


def test_pointer_on_a_child_of_the_notice_is_still_inside(root, fast, monkeypatch):
    notify(root, "Copied")
    host = host_for(root)
    host._on_enter()
    monkeypatch.setattr(host.frame, "winfo_containing", lambda x, y: host.close_button)
    host._on_leave()
    assert host._hovered


def test_the_same_message_again_extends_the_notice(root, monkeypatch):
    monkeypatch.setattr(notice_mod, "BASE_MS", 200)
    monkeypatch.setattr(notice_mod, "PER_CHAR_MS", 0)
    notify(root, "Type a question first.", "warning")
    _pump(root, 130)
    notify(root, "Type a question first.", "warning")
    _pump(root, 130)
    assert host_for(root).visible  # 260 ms in: the first timer alone would have ended at 200
    _pump(root, 300)
    assert not host_for(root).visible
