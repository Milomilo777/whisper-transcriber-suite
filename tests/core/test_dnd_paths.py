r"""Drag-and-drop path parsing, especially UNC network shares.

A file dragged from a network share ``\\server\share\file.mp4`` used to
be silently ignored: ``Tk.splitlist`` collapses the leading ``\\`` of a
brace-wrapped UNC path down to a single backslash, so the path is no
longer a valid UNC and the later ``os.path.isfile`` gate fails. The pure
``_split_dnd_paths`` helper splits the tkdnd wire format (space-separated
tokens, space-bearing tokens wrapped in ``{...}``) WITHOUT touching the
backslashes, so UNC drops survive. These tests pin that helper and drive
``App._on_drop`` with a stubbed Tk object — no GUI, no tkinterdnd2.
"""
from __future__ import annotations

import types

import pytest

pytest.importorskip("tkinter")

from app.app import App, _split_dnd_paths


# --- the pure splitter -------------------------------------------------

def test_braced_unc_with_space_keeps_double_backslash():
    raw = r"{\\server\share\my file.mp4}"
    assert _split_dnd_paths(raw) == [r"\\server\share\my file.mp4"]


def test_braced_unc_without_space():
    # tkdnd still braces some tokens; a UNC with no space must survive too.
    raw = r"{\\server\share\clip.mp4}"
    assert _split_dnd_paths(raw) == [r"\\server\share\clip.mp4"]


def test_bare_unc_without_space():
    # No braces at all (no space in the path) — passes through verbatim.
    raw = r"\\server\share\clip.mp4"
    assert _split_dnd_paths(raw) == [r"\\server\share\clip.mp4"]


def test_plain_local_path():
    raw = r"C:\path\file.mp4"
    assert _split_dnd_paths(raw) == [r"C:\path\file.mp4"]


def test_local_path_with_space_is_braced():
    raw = r"{C:\my videos\file.mp4}"
    assert _split_dnd_paths(raw) == [r"C:\my videos\file.mp4"]


def test_mapped_drive_path():
    raw = r"Z:\clip.mp4"
    assert _split_dnd_paths(raw) == [r"Z:\clip.mp4"]


def test_multi_file_drop_mixed():
    raw = r"C:\a.mp4 {\\server\share\my file.mp4} Z:\c.mp4"
    assert _split_dnd_paths(raw) == [
        r"C:\a.mp4",
        r"\\server\share\my file.mp4",
        r"Z:\c.mp4",
    ]


def test_empty_and_whitespace():
    assert _split_dnd_paths("") == []
    assert _split_dnd_paths("   ") == []


def test_unbalanced_brace_takes_remainder():
    raw = r"{\\server\share\file.mp4"
    assert _split_dnd_paths(raw) == [r"\\server\share\file.mp4"]


# --- _on_drop end-to-end with a stubbed Tk -----------------------------

class _FakeVar:
    def __init__(self) -> None:
        self.value: str = ""

    def set(self, v: str) -> None:
        self.value = v


class _FakeNotebook:
    def __init__(self) -> None:
        self.selected = None

    def select(self, tab) -> None:  # noqa: ANN001
        self.selected = tab


def _fake_app() -> types.SimpleNamespace:
    """A minimal stand-in exposing only what _on_drop touches."""
    return types.SimpleNamespace(
        fv=_FakeVar(),
        nb=_FakeNotebook(),
        t1="transcribe-tab",
        t3="download-tab",
        enqueued=[],
        logs=[],
        log=lambda msg: None,  # set below to capture
        add=lambda: None,
        _bulk_enqueue=lambda paths: 0,
    )


def _drive(app: types.SimpleNamespace, raw: str) -> None:
    app.log = app.logs.append
    # The multi-file branch now calls _bulk_enqueue(paths) once (BUG I:
    # gate the ~3 GB modal + tab-switch + refresh ONCE instead of per-file).
    def _bulk(paths):
        app.enqueued.extend(paths)
        return len(paths)
    app._bulk_enqueue = _bulk
    # _on_drop splits the payload and hands the items to open_paths.
    app.open_paths = lambda items, **kw: App.open_paths(app, items, **kw)  # type: ignore[arg-type]
    event = types.SimpleNamespace(data=raw)
    App._on_drop(app, event)  # type: ignore[arg-type]


def test_on_drop_accepts_unc_file(monkeypatch):
    """A single dragged UNC file lands in the Transcribe field intact."""
    unc = r"\\server\share\my file.mp4"
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: s == unc)
    app = _fake_app()
    _drive(app, r"{\\server\share\my file.mp4}")
    assert app.fv.value == unc
    assert app.nb.selected == app.t1


def test_on_drop_local_file_still_works(monkeypatch):
    local = r"C:\videos\clip.mp4"
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: s == local)
    app = _fake_app()
    _drive(app, local)
    assert app.fv.value == local
    assert app.nb.selected == app.t1


def test_on_drop_multi_file_enqueues_each(monkeypatch):
    files = {r"C:\a.mp4", r"\\server\share\my file.mp4", r"Z:\c.mp4"}
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: s in files)
    app = _fake_app()
    _drive(app, r"C:\a.mp4 {\\server\share\my file.mp4} Z:\c.mp4")
    assert set(app.enqueued) == files


def test_on_drop_url_routes_to_download_tab(monkeypatch):
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: False)
    app = _fake_app()
    app.download_url_var = _FakeVar()
    _drive(app, "https://example.com/video")
    assert app.download_url_var.value == "https://example.com/video"
    assert app.nb.selected == app.t3


# --- folder drops + never-silent junk drops ----------------------------

import os

from app.app import _media_files_in_folder


def test_media_files_in_folder_filters_and_sorts(tmp_path):
    (tmp_path / "b.mp4").write_bytes(b"x")
    (tmp_path / "a.wav").write_bytes(b"x")
    (tmp_path / "notes.txt").write_bytes(b"x")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "c.mp4").write_bytes(b"x")  # below top level — must NOT be picked up
    found = _media_files_in_folder(str(tmp_path))
    assert [os.path.basename(p) for p in found] == ["a.wav", "b.mp4"]


def test_media_files_in_folder_missing_folder_is_empty():
    assert _media_files_in_folder(r"C:\definitely\not\here\at-all") == []


def test_on_drop_folder_with_media_enqueues_them(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.wav").write_bytes(b"x")
    app = _fake_app()
    _drive(app, "{" + str(tmp_path) + "}")
    assert sorted(os.path.basename(p) for p in app.enqueued) == ["a.mp4", "b.wav"]


def test_on_drop_folder_single_media_lands_in_transcribe_field(tmp_path):
    media = tmp_path / "only.mp4"
    media.write_bytes(b"x")
    app = _fake_app()
    _drive(app, "{" + str(tmp_path) + "}")
    assert app.fv.value == str(media)
    assert app.nb.selected == app.t1


def test_on_drop_empty_folder_is_reported_not_silent(tmp_path):
    app = _fake_app()
    _drive(app, "{" + str(tmp_path) + "}")
    assert app.enqueued == []
    assert app.fv.value == ""
    assert any("no media files" in msg for msg in app.logs)


def test_on_drop_nonexistent_path_is_reported_not_silent():
    app = _fake_app()
    _drive(app, r"C:\gone\away.mp4")
    assert any("Ignored 1 dropped item" in msg for msg in app.logs)


# --- BUG I: bulk enqueue gates the model/worker readiness ONCE -------------


def test_bulk_enqueue_gates_once_and_refreshes_once(monkeypatch):
    """Multi-file enqueue must gate model/worker readiness ONCE up front, then
    enqueue a task per existing path and refresh() ONCE — not re-pop the
    ~3 GB modal + tab-switch + refresh per file like the old add() loop."""
    files = {r"C:\a.mp4", r"C:\b.mp4", r"C:\c.mp4"}
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: s in files)

    calls = {"ready": 0, "refresh": 0, "opts": 0}

    app = types.SimpleNamespace(
        queue=[],
        nb=_FakeNotebook(),
        t2="queue-tab",
        pb={"value": 99},
        _ensure_transcribe_ready=lambda: (calls.__setitem__("ready", calls["ready"] + 1), True)[1],
        _apply_task_options=lambda _t: calls.__setitem__("opts", calls["opts"] + 1),
        refresh=lambda: calls.__setitem__("refresh", calls["refresh"] + 1),
    )

    count = App._bulk_enqueue(app, list(files))  # type: ignore[arg-type]

    assert count == 3
    assert len(app.queue) == 3            # one task per existing path
    assert calls["ready"] == 1            # the gate ran exactly ONCE
    assert calls["refresh"] == 1          # one refresh for the whole batch
    assert calls["opts"] == 3             # language/clip options applied per task
    assert app.nb.selected == app.t2      # switched to the queue tab once
    assert app.pb["value"] == 0


def test_bulk_enqueue_declined_gate_enqueues_nothing(monkeypatch):
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: True)
    calls = {"refresh": 0}
    app = types.SimpleNamespace(
        queue=[],
        nb=_FakeNotebook(),
        t2="queue-tab",
        pb={"value": 0},
        _ensure_transcribe_ready=lambda: False,   # user declined the model download
        _apply_task_options=lambda _t: None,
        refresh=lambda: calls.__setitem__("refresh", calls["refresh"] + 1),
    )
    count = App._bulk_enqueue(app, [r"C:\a.mp4", r"C:\b.mp4"])  # type: ignore[arg-type]
    assert count == 0
    assert app.queue == []
    assert calls["refresh"] == 0


def test_bulk_enqueue_skips_missing_files(monkeypatch):
    # Only files that still exist on disk are enqueued.
    monkeypatch.setattr("app.app.os.path.isfile", lambda s: s == r"C:\real.mp4")
    app = types.SimpleNamespace(
        queue=[],
        nb=_FakeNotebook(),
        t2="queue-tab",
        pb={"value": 0},
        _ensure_transcribe_ready=lambda: True,
        _apply_task_options=lambda _t: None,
        refresh=lambda: None,
    )
    count = App._bulk_enqueue(app, [r"C:\real.mp4", r"C:\ghost.mp4"])  # type: ignore[arg-type]
    assert count == 1
    assert len(app.queue) == 1
