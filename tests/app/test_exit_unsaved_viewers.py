"""Closing the app while a transcript viewer holds unsaved edits asks before it throws them away.

Every way out goes through ``App.on_exit``: the window's close button, File -> Exit and Ctrl+Q
(``_force_exit``), the tray's Exit, and on macOS Cmd+Q / the app-menu Quit / the Dock Quit
(``::tk::mac::Quit``). Before anything irreversible (stopping the workers, recording the exit
reason, destroying the window) each viewer with unsaved edits gets Save / Discard / Cancel:

* Cancel leaves the whole app running and nothing stopped;
* Save uses the viewer's own save and must succeed before the exit goes on;
* Discard exits without writing;
* the tray's minimise-instead-of-exit never asks.

The tests use a real Tk root (a bare ``App``, as ``test_quit_during_job`` does) and real viewers
on real transcript files.
"""
from __future__ import annotations

import json
import os
import tkinter as tk
import types
from pathlib import Path
from typing import Any, Callable

import pytest

from app import app as app_module
from app.app import App
from app.dialogs import transcript_viewer as tv
from app.widgets.tray import TrayController
from core.transcriber import _write_outputs


def _segments() -> list[dict[str, Any]]:
    return [
        {"start": 0.0, "end": 1.25, "text": "Hello world"},
        {"start": 1.25, "end": 3.5, "text": "Second line here"},
    ]


@pytest.fixture
def calls() -> list[str]:
    return []


@pytest.fixture
def app(calls: list[str], monkeypatch: pytest.MonkeyPatch):
    """A real Tk root of class App, wired just enough for on_exit."""
    root = App.__new__(App)
    try:
        tk.Tk.__init__(root)
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    root.withdraw()
    root.app_config = {}
    root.tray = None
    root._exit_from_tray = True
    root._closing = False
    root._folder_watcher = None
    root.history = None
    root.queue = []
    root.download_queue = []
    root.log = lambda *_a, **_k: None  # type: ignore[method-assign]
    root._save_window_geometry = lambda: None  # type: ignore[method-assign]
    root._shutdown_server_on_exit = lambda: None  # type: ignore[method-assign]
    root.transcription_service = types.SimpleNamespace(  # type: ignore[assignment]
        stop_all=lambda **_k: calls.append("stop_all"),
        settle_done_on_exit=lambda: calls.append("settle"),
    )
    # The real teardown would end the test's own Tk; record it and tear down at the end.
    root.destroy = lambda: calls.append("destroy")  # type: ignore[method-assign]
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: True)
    monkeypatch.setattr(app_module, "stop_live_session", lambda _a: None)
    monkeypatch.setattr(app_module, "stop_voice_clone_worker", lambda _a: None)
    yield root
    tv._OPEN_VIEWERS.clear()
    tk.Tk.destroy(root)


def _make_json(tmp_path: Path, name: str = "talk") -> str:
    base = str(tmp_path / name)
    written = _write_outputs(base, _segments(), str(tmp_path / f"{name}.mp4"), ["json", "srt"])
    return next(p for p in written if p.endswith(".json"))


def _open_dirty(app: App, json_path: str, text: str = "Edited text") -> tv.TranscriptViewer:
    viewer = tv.TranscriptViewer(app, json_path)
    viewer.withdraw()
    viewer.segments[0]["text"] = text
    viewer._dirty = True
    return viewer


def _answer(monkeypatch: pytest.MonkeyPatch, *answers: bool | None) -> list[dict[str, Any]]:
    """Script the viewer questions (Yes = Save, No = Discard, None = Cancel)."""
    asked: list[dict[str, Any]] = []
    queue = list(answers)

    def _ask(title: str, message: str, **kw: Any) -> bool | None:
        asked.append({"title": title, "message": message, "parent": kw.get("parent")})
        return queue.pop(0)

    monkeypatch.setattr(tv.messagebox, "askyesnocancel", _ask)
    return asked


def _text_on_disk(json_path: str) -> str:
    with open(json_path, encoding="utf-8-sig") as f:
        return json.load(f)[0]["text"]


def _quit_paths(app: App) -> list[tuple[str, Callable[[], None]]]:
    """Each way the user can leave, as a zero-argument callable."""
    real_call = app.tk.call

    class _Tk:
        def __getattr__(self, name: str) -> Any:
            return getattr(app.tk, name)

        def call(self, *args: Any) -> Any:
            if args == ("tk", "windowingsystem"):
                return "aqua"  # the real windowing system here is win32/x11
            return real_call(*args)

    def _cmd_q() -> None:
        # What macOS does for Cmd+Q: install the command, then Tk runs it.
        proxy = types.SimpleNamespace(
            tk=_Tk(), createcommand=app.createcommand, _force_exit=app._force_exit,
        )
        App._install_quit_handler(proxy)  # type: ignore[arg-type]
        app.tk.call("::tk::mac::Quit")

    def _close_button() -> None:
        app._exit_from_tray = False
        app.on_exit()

    return [
        ("window close button", _close_button),
        ("File-Exit / Ctrl+Q / tray Exit", app._force_exit),
        ("macOS Cmd+Q", _cmd_q),
    ]


PATH_IDS = ["window close button", "File-Exit / Ctrl+Q / tray Exit", "macOS Cmd+Q"]


# ------------------------------------------------------------------ the four answers


@pytest.mark.parametrize("path", PATH_IDS)
def test_cancel_keeps_the_app_running_and_stops_nothing(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    json_path = _make_json(tmp_path)
    before = Path(json_path).read_bytes()
    viewer = _open_dirty(app, json_path)
    asked = _answer(monkeypatch, None)

    dict(_quit_paths(app))[path]()

    assert len(asked) == 1
    assert calls == []  # no stop_all, no destroy
    assert viewer.winfo_exists() and viewer._dirty
    assert Path(json_path).read_bytes() == before
    assert app._exit_from_tray is False  # the one-shot override is released
    assert getattr(app, "_exit_prompt_open", False) is False
    assert app._closing is False  # the queue pump keeps running


@pytest.mark.parametrize("path", PATH_IDS)
def test_save_writes_the_edit_first_then_the_exit_goes_on(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    json_path = _make_json(tmp_path)
    viewer = _open_dirty(app, json_path, "Saved before exit")
    _answer(monkeypatch, True)
    real_save = viewer._save_changes
    viewer._save_changes = lambda: (calls.append("save"), real_save())[1]  # type: ignore[method-assign]

    dict(_quit_paths(app))[path]()

    assert _text_on_disk(json_path) == "Saved before exit"
    assert calls == ["save", "stop_all", "settle", "destroy"]
    srt = Path(json_path).with_suffix(".srt").read_text(encoding="utf-8")
    assert "Saved before exit" in srt  # the subtitle file beside it follows the save


@pytest.mark.parametrize("path", PATH_IDS)
def test_discard_exits_without_writing(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, path: str,
) -> None:
    json_path = _make_json(tmp_path)
    before = Path(json_path).read_bytes()
    _open_dirty(app, json_path)
    _answer(monkeypatch, False)

    dict(_quit_paths(app))[path]()

    assert Path(json_path).read_bytes() == before
    assert calls == ["stop_all", "settle", "destroy"]


def test_a_failed_save_aborts_the_exit_and_shows_the_error(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = _make_json(tmp_path)
    before = Path(json_path).read_bytes()
    viewer = _open_dirty(app, json_path)
    _answer(monkeypatch, True)
    errors: list[tuple[str, str]] = []
    monkeypatch.setattr(tv, "show_error", lambda _w, title, msg, detail=None: errors.append((title, msg)))

    def _boom(_src: str, _dst: str) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(tv.os, "replace", _boom)

    app.on_exit()

    assert errors and errors[0][0] == "Save failed"
    assert calls == []  # nothing stopped, window still there
    assert viewer.winfo_exists() and viewer._dirty
    assert Path(json_path).read_bytes() == before
    assert app._exit_from_tray is False and app._closing is False


def test_an_unexpected_error_inside_save_aborts_the_exit_and_is_shown(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer = _open_dirty(app, _make_json(tmp_path))
    _answer(monkeypatch, True)
    errors: list[str] = []
    monkeypatch.setattr(tv, "show_error", lambda _w, title, msg, detail=None: errors.append(title))

    def _bug() -> None:
        raise RuntimeError("bug")

    viewer._save_changes = _bug  # type: ignore[method-assign]

    app.on_exit()

    assert errors == ["Save failed"]
    assert calls == []


def test_declining_to_overwrite_a_file_changed_on_disk_keeps_the_app_open(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = _make_json(tmp_path)
    viewer = _open_dirty(app, json_path)
    _answer(monkeypatch, True)
    Path(json_path).write_text("[]", encoding="utf-8")  # someone else changed it
    asked_overwrite: list[str] = []

    def _no(title: str, *_a: Any, **_k: Any) -> bool:
        asked_overwrite.append(title)
        return False

    monkeypatch.setattr(tv.messagebox, "askyesno", _no)

    app.on_exit()

    assert asked_overwrite == ["Transcript changed on disk"]
    assert calls == []
    assert viewer._dirty


# ------------------------------------------------------------------ no prompt cases


def test_no_prompt_when_no_viewer_is_dirty(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    clean = tv.TranscriptViewer(app, _make_json(tmp_path))
    clean.withdraw()
    asked = _answer(monkeypatch)  # any question would pop from an empty list

    app.on_exit()

    assert asked == []
    assert calls == ["stop_all", "settle", "destroy"]


def test_no_prompt_without_any_viewer(
    app: App, calls: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked = _answer(monkeypatch)
    app.on_exit()
    assert asked == [] and calls == ["stop_all", "settle", "destroy"]


def test_minimise_to_tray_does_not_ask(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer = _open_dirty(app, _make_json(tmp_path))
    asked = _answer(monkeypatch)
    app._exit_from_tray = False
    app.app_config = {"minimise_to_tray": True}
    app.tray = types.SimpleNamespace(is_supported=lambda: True)  # type: ignore[assignment]

    app.on_exit()

    assert asked == [] and calls == []
    assert viewer.winfo_exists() and viewer._dirty  # the edits are still there, untouched


def test_tray_exit_does_ask(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tray's Exit item sets the override and calls on_exit: that IS an exit."""
    _open_dirty(app, _make_json(tmp_path))
    asked = _answer(monkeypatch, None)
    app.app_config = {"minimise_to_tray": True}
    app.tray = types.SimpleNamespace(is_supported=lambda: True)  # type: ignore[assignment]
    app._exit_from_tray = True  # what TrayController._exit_app does

    app.on_exit()

    assert len(asked) == 1 and calls == []


def test_a_viewer_that_is_closing_or_gone_is_not_asked(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    gone = _open_dirty(app, _make_json(tmp_path, "a"))
    closing = _open_dirty(app, _make_json(tmp_path, "b"))
    closing._closing = True
    asked = _answer(monkeypatch)
    # A stale registry entry: the window was destroyed without unregistering.
    tv._OPEN_VIEWERS["stale"] = gone
    tk.Toplevel.destroy(gone)

    app.on_exit()

    assert asked == []
    assert calls == ["stop_all", "settle", "destroy"]


def test_a_viewer_hidden_with_the_tray_window_is_shown_for_its_question(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tray Exit while the app is hidden: the viewer follows its parent, so show both."""
    viewer = _open_dirty(app, _make_json(tmp_path))
    app.withdraw()
    seen: list[str] = []

    def _ask(*_a: Any, **_k: Any) -> None:
        seen.append(app.state())  # what the user sees while the question is open
        return None

    monkeypatch.setattr(tv.messagebox, "askyesnocancel", _ask)

    app.on_exit()

    assert seen == ["normal"]
    assert calls == [] and viewer.winfo_exists()


# ------------------------------------------------------------------ several viewers


def test_each_dirty_viewer_gets_its_own_prompt_in_front_and_names_its_file(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = _open_dirty(app, _make_json(tmp_path, "alpha"), "A edited")
    b = _open_dirty(app, _make_json(tmp_path, "beta"), "B edited")
    clean = tv.TranscriptViewer(app, _make_json(tmp_path, "gamma"))
    clean.withdraw()
    fronted: list[Any] = []
    for v in (a, b):
        v.lift = lambda *_a, _v=v, **_k: fronted.append(_v)  # type: ignore[method-assign]
    asked = _answer(monkeypatch, True, False)

    app.on_exit()

    assert [q["parent"] for q in asked] == [a, b] or [q["parent"] for q in asked] == [b, a]
    assert set(fronted) == {a, b}
    for q in asked:
        name = "alpha" if q["parent"] is a else "beta"
        assert name in q["message"]
    assert calls == ["stop_all", "settle", "destroy"]
    saved, discarded = (a, b) if asked[0]["parent"] is a else (b, a)
    assert _text_on_disk(saved.json_path) != "Hello world"
    assert _text_on_disk(discarded.json_path) == "Hello world"


def test_cancel_on_the_second_viewer_keeps_the_app_and_leaves_the_first_saved(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    a = _open_dirty(app, _make_json(tmp_path, "alpha"), "A saved")
    b = _open_dirty(app, _make_json(tmp_path, "beta"), "B edited")
    asked = _answer(monkeypatch, True, None)

    app.on_exit()

    assert len(asked) == 2
    first = asked[0]["parent"]
    second = asked[1]["parent"]
    assert calls == []
    assert not first._dirty and first.winfo_exists()  # saved, still open
    assert second._dirty and second.winfo_exists()  # untouched
    assert {first, second} == {a, b}


# ------------------------------------------------------------------ prompt order


def test_the_order_is_queued_tasks_then_viewers_then_the_live_transcript(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    order: list[str] = []
    _open_dirty(app, _make_json(tmp_path))
    app.queue = [types.SimpleNamespace(status="running", process=None, history_id=None)]
    monkeypatch.setattr(
        app_module.messagebox, "askyesno", lambda *_a, **_k: order.append("queue") or True)
    monkeypatch.setattr(
        tv.messagebox, "askyesnocancel", lambda *_a, **_k: order.append("viewer") or False)
    monkeypatch.setattr(
        app_module, "live_save_before_exit", lambda _a: order.append("live") or True)

    app.on_exit()

    assert order == ["queue", "viewer", "live"]
    assert calls == ["stop_all", "settle", "destroy"]


def test_a_declined_queue_question_never_reaches_the_viewers(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_dirty(app, _make_json(tmp_path))
    app.queue = [types.SimpleNamespace(status="running", process=None, history_id=None)]
    monkeypatch.setattr(app_module.messagebox, "askyesno", lambda *_a, **_k: False)
    asked = _answer(monkeypatch)

    app.on_exit()

    assert asked == [] and calls == []


def test_cancelling_a_viewer_never_reaches_the_live_question_or_the_teardown(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_dirty(app, _make_json(tmp_path))
    _answer(monkeypatch, None)
    live: list[int] = []
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: live.append(1) or True)

    app.on_exit()

    assert live == [] and calls == []


def test_a_cancelled_live_question_after_a_viewer_save_keeps_the_app_open(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Save is kept (it is what the user chose); the next exit does not ask the viewer again."""
    json_path = _make_json(tmp_path)
    viewer = _open_dirty(app, json_path, "Kept")
    asked = _answer(monkeypatch, True)
    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: False)

    app.on_exit()
    assert calls == [] and not viewer._dirty and _text_on_disk(json_path) == "Kept"

    monkeypatch.setattr(app_module, "live_save_before_exit", lambda _a: True)
    app._exit_from_tray = True
    app.on_exit()
    assert len(asked) == 1  # not asked a second time
    assert calls == ["stop_all", "settle", "destroy"]


def test_a_second_quit_while_the_viewer_question_is_open_is_ignored(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_dirty(app, _make_json(tmp_path))
    asked: list[int] = []

    def _ask(*_a: Any, **_k: Any) -> None:
        asked.append(1)
        app._exit_from_tray = True
        app.on_exit()  # the nested Cmd+Q
        return None

    monkeypatch.setattr(tv.messagebox, "askyesnocancel", _ask)

    app.on_exit()

    assert asked == [1] and calls == []
    assert getattr(app, "_exit_prompt_open", False) is False


def test_the_unsaved_prompt_text_is_plain_and_says_what_each_button_does(
    app: App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_dirty(app, _make_json(tmp_path))
    asked = _answer(monkeypatch, None)
    app.on_exit()
    text = asked[0]["message"]
    assert "talk.json" in text
    for word in ("Yes", "No", "Cancel"):
        assert word in text


# ------------------------------------------------------------------ review follow-ups


def _tray_on(app: App) -> list[int]:
    """Minimise-to-tray on with a working tray; returns the list withdraw() appends to."""
    withdrawn: list[int] = []
    app.deiconify()
    app.withdraw = lambda: withdrawn.append(1)  # type: ignore[method-assign]
    app.app_config = {"minimise_to_tray": True}
    app.tray = types.SimpleNamespace(is_supported=lambda: True)  # type: ignore[assignment]
    return withdrawn


def test_pressing_close_during_the_viewer_question_does_not_hide_the_app(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With minimise-to-tray on, X while a question is open must not withdraw its owner."""
    _open_dirty(app, _make_json(tmp_path))
    withdrawn = _tray_on(app)
    app._exit_from_tray = True  # tray Exit opened the question
    pressed: list[int] = []

    def _ask(*_a: Any, **_k: Any) -> None:
        app._exit_from_tray = False  # the window's X button
        app.on_exit()
        pressed.append(1)
        return None

    monkeypatch.setattr(tv.messagebox, "askyesnocancel", _ask)

    app.on_exit()

    assert pressed == [1] and withdrawn == [] and calls == []


def test_close_still_minimises_to_the_tray_when_no_question_is_open(
    app: App, calls: list[str], monkeypatch: pytest.MonkeyPatch,
) -> None:
    withdrawn = _tray_on(app)
    app._exit_from_tray = False
    app.on_exit()
    assert withdrawn == [1] and calls == []


def test_the_tray_hide_item_is_ignored_while_a_question_is_open() -> None:
    hidden: list[int] = []
    app_ns = types.SimpleNamespace(withdraw=lambda: hidden.append(1), _exit_prompt_open=True)
    TrayController._hide_window(types.SimpleNamespace(app=app_ns))  # type: ignore[arg-type]
    assert hidden == []
    app_ns._exit_prompt_open = False
    TrayController._hide_window(types.SimpleNamespace(app=app_ns))  # type: ignore[arg-type]
    assert hidden == [1]


def test_the_viewer_is_mapped_and_in_front_before_its_question(
    app: App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    viewer = _open_dirty(app, _make_json(tmp_path))
    order: list[str] = []
    for name in ("deiconify", "lift", "update_idletasks"):
        real = getattr(viewer, name)
        setattr(viewer, name, lambda *a, _n=name, _r=real, **k: (order.append(_n), _r(*a, **k))[1])
    monkeypatch.setattr(
        tv.messagebox, "askyesnocancel", lambda *_a, **_k: order.append("ask") or None)

    app.on_exit()

    assert order.index("deiconify") < order.index("lift") < order.index("ask")
    assert "update_idletasks" in order[order.index("lift"):order.index("ask")]


def test_declining_the_overwrite_says_why_the_app_stays_open(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = _make_json(tmp_path)
    _open_dirty(app, json_path)
    _answer(monkeypatch, True)
    Path(json_path).write_text("[]", encoding="utf-8")
    monkeypatch.setattr(tv.messagebox, "askyesno", lambda *_a, **_k: False)
    notices: list[tuple[str, str]] = []
    monkeypatch.setattr(tv, "notify", lambda _w, text, kind="info": notices.append((text, kind)))

    app.on_exit()

    assert calls == []
    assert ("Not saved, so the app stays open.", "warning") in notices


def test_a_failed_write_also_says_the_app_stays_open(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_dirty(app, _make_json(tmp_path))
    _answer(monkeypatch, True)
    monkeypatch.setattr(tv, "show_error", lambda *_a, **_k: None)
    monkeypatch.setattr(tv.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("full")))
    notices: list[str] = []
    monkeypatch.setattr(tv, "notify", lambda _w, text, kind="info": notices.append(text))

    app.on_exit()

    assert calls == [] and "Not saved, so the app stays open." in notices


def test_a_failing_sibling_update_after_a_good_write_does_not_stop_the_exit(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = _make_json(tmp_path)
    viewer = _open_dirty(app, json_path, "Written first")
    _answer(monkeypatch, True)
    errors: list[str] = []
    monkeypatch.setattr(tv, "show_error", lambda _w, title, *_a, **_k: errors.append(title))
    notices: list[str] = []
    monkeypatch.setattr(tv, "notify", lambda _w, text, kind="info": notices.append(text))

    def _boom() -> Any:
        raise RuntimeError("sibling bug")

    viewer._queue_exports = _boom  # type: ignore[method-assign]

    app.on_exit()

    assert _text_on_disk(json_path) == "Written first"  # the transcript itself is saved
    assert errors == []  # no "could not write your changes"
    assert calls == ["stop_all", "settle", "destroy"]
    assert any("saved" in n.lower() and "subtitle" in n.lower() for n in notices)


def test_a_failing_notice_after_a_good_write_does_not_stop_the_exit(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    json_path = _make_json(tmp_path)
    _open_dirty(app, json_path, "Written first")
    _answer(monkeypatch, True)
    errors: list[str] = []
    monkeypatch.setattr(tv, "show_error", lambda _w, title, *_a, **_k: errors.append(title))

    def _boom(*_a: Any, **_k: Any) -> None:
        raise RuntimeError("toast bug")

    monkeypatch.setattr(tv, "notify", _boom)

    app.on_exit()

    assert _text_on_disk(json_path) == "Written first"
    assert errors == [] and calls == ["stop_all", "settle", "destroy"]


def test_two_viewers_with_the_same_file_name_show_their_folders(
    app: App, calls: list[str], tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "one").mkdir()
    (tmp_path / "two").mkdir()
    _open_dirty(app, _make_json(tmp_path / "one", "talk"))
    _open_dirty(app, _make_json(tmp_path / "two", "talk"))
    asked = _answer(monkeypatch, False, False)

    app.on_exit()

    folders = sorted(q["message"] for q in asked)
    assert "one" in folders[0] + folders[1] and "two" in folders[0] + folders[1]
    for q in asked:
        parent_dir = os.path.dirname(q["parent"].json_path)
        assert parent_dir in q["message"]


def test_a_unique_file_name_does_not_repeat_the_folder(
    app: App, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _open_dirty(app, _make_json(tmp_path, "alpha"))
    _open_dirty(app, _make_json(tmp_path, "beta"))
    asked = _answer(monkeypatch, False, False)
    app.on_exit()
    for q in asked:
        assert str(tmp_path) not in q["message"]
