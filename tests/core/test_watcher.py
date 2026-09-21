"""Tests for the watched-folder dedup + stability check.

Drives ``core.watcher.FolderWatcher`` and the ``App._enqueue_watched_file``
stability ladder against a fake clock so we don't actually wait 1.2 s
for each iteration.
"""
from __future__ import annotations

import os
import sys
import types

import pytest


def test_watcher_is_available_returns_false_without_watchdog(monkeypatch):
    monkeypatch.setitem(sys.modules, "watchdog", None)
    from core import watcher as w
    assert w.is_available() is False
    assert "watchdog" in w.availability_reason()


def test_watcher_media_extension_filter():
    """Internal extension set must include the formats we list in
    the GUI's Browse... filter — drops out of sync if someone adds
    a new extension only in one place."""
    from core import watcher as w
    expected = {".mp3", ".mp4", ".wav", ".m4a", ".mkv", ".webm"}
    assert expected.issubset(w._MEDIA_EXTENSIONS)


def test_is_media_file_extension_gate():
    """The public helper shared with the drag-and-drop folder handler."""
    from core import watcher as w
    assert w.is_media_file("clip.MP4")           # case-insensitive
    assert w.is_media_file(r"C:\x\audio.flac")   # full paths fine
    assert not w.is_media_file("notes.txt")
    assert not w.is_media_file("no_extension")


def test_folder_watcher_stop_when_unavailable(monkeypatch, tmp_path):
    """FolderWatcher.stop on an unstarted instance is a noop."""
    from core import watcher as w
    fw = w.FolderWatcher(str(tmp_path), lambda _p: None)
    # Must not raise.
    fw.stop()
    assert fw.is_running() is False


def test_folder_watcher_start_raises_without_watchdog(monkeypatch, tmp_path):
    """When watchdog isn't installed, start() raises a clear
    RuntimeError instead of crashing with an obscure ImportError."""
    from core import watcher as w
    monkeypatch.setattr(w, "is_available", lambda: False)
    monkeypatch.setattr(
        w, "availability_reason",
        lambda: "watchdog Python package not installed",
    )
    fw = w.FolderWatcher(str(tmp_path), lambda _p: None)
    with pytest.raises(RuntimeError, match="watchdog"):
        fw.start()


def test_folder_watcher_lock_is_reentrant(tmp_path):
    """Regression: FolderWatcher.start() acquires self._lock and
    then calls self.stop() which acquires it again. With a plain
    threading.Lock this deadlocks forever; RLock fixes it.
    """
    from core import watcher as w
    fw = w.FolderWatcher(str(tmp_path), lambda _p: None)
    # The lock attribute must support re-entry from the same thread.
    assert fw._lock.acquire(blocking=False)
    # Acquire again from the same thread — must succeed (RLock semantic).
    assert fw._lock.acquire(blocking=False)
    fw._lock.release()
    fw._lock.release()


# --- event dispatch (created vs moved) -------------------------------------


class _Event:
    """Minimal stand-in for a watchdog FileSystemEvent."""

    def __init__(self, src_path="", dest_path="", is_directory=False):
        self.src_path = src_path
        self.dest_path = dest_path
        self.is_directory = is_directory


def _install_fake_watchdog(monkeypatch, w):
    """Register fake ``watchdog.*`` modules and return the Observer instances.

    The handler class is defined inside ``FolderWatcher.start()``, so the only
    way to drive it hermetically is to capture the instance handed to
    ``Observer.schedule``.
    """
    instances = []

    class _FakeObserver:
        def __init__(self):
            self.handler = None
            self.path = None
            self.recursive = None
            self.daemon = False
            self.started = False
            self.stopped = False
            instances.append(self)

        def schedule(self, handler, path, recursive=False):
            self.handler = handler
            self.path = path
            self.recursive = recursive

        def start(self):
            self.started = True

        def stop(self):
            self.stopped = True

        def join(self, timeout=None):
            pass

        def is_alive(self):
            return self.started and not self.stopped

    events_mod = types.ModuleType("watchdog.events")
    events_mod.FileSystemEventHandler = object
    observers_mod = types.ModuleType("watchdog.observers")
    observers_mod.Observer = _FakeObserver
    pkg = types.ModuleType("watchdog")
    pkg.events = events_mod  # type: ignore[attr-defined]
    pkg.observers = observers_mod  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "watchdog", pkg)
    monkeypatch.setitem(sys.modules, "watchdog.events", events_mod)
    monkeypatch.setitem(sys.modules, "watchdog.observers", observers_mod)
    monkeypatch.setattr(w, "is_available", lambda: True)
    return instances


def test_folder_watcher_dispatches_moved_in_media(monkeypatch, tmp_path):
    """A media file MOVED into the folder (Explorer's default drag on the
    same volume; a downloader's ``.part`` -> final rename) must enqueue it.
    Regression: only on_created was handled, so the move was silently lost.
    """
    from core import watcher as w
    instances = _install_fake_watchdog(monkeypatch, w)
    got = []
    fw = w.FolderWatcher(str(tmp_path), got.append)
    fw.start()

    handler = instances[-1].handler
    dest = str(tmp_path / "clip.mp4")
    handler.on_moved(_Event(src_path="C:\\elsewhere\\clip.mp4", dest_path=dest))

    assert got == [dest]

    # A bytes dest_path (possible on some watchdog backends) is decoded too.
    got.clear()
    bytes_dest = os.fsencode(str(tmp_path / "bytes.wav"))
    handler.on_moved(_Event(dest_path=bytes_dest))
    assert got == [os.fsdecode(bytes_dest)]
    fw.stop()


def test_folder_watcher_moved_out_is_ignored(monkeypatch, tmp_path):
    """A move OUT of the watched folder must not enqueue the file now living
    somewhere else."""
    from core import watcher as w
    instances = _install_fake_watchdog(monkeypatch, w)
    got = []
    fw = w.FolderWatcher(str(tmp_path), got.append)
    fw.start()

    handler = instances[-1].handler
    handler.on_moved(
        _Event(src_path=str(tmp_path / "clip.mp4"),
               dest_path=str(tmp_path.parent / "clip.mp4"))
    )

    assert got == []
    fw.stop()


def test_folder_watcher_moved_non_media_and_dirs_ignored(monkeypatch, tmp_path):
    from core import watcher as w
    instances = _install_fake_watchdog(monkeypatch, w)
    got = []
    fw = w.FolderWatcher(str(tmp_path), got.append)
    fw.start()

    handler = instances[-1].handler
    handler.on_moved(_Event(dest_path=str(tmp_path / "notes.txt")))
    handler.on_moved(
        _Event(dest_path=str(tmp_path / "subdir"), is_directory=True)
    )

    assert got == []
    fw.stop()


def test_folder_watcher_created_still_dispatches(monkeypatch, tmp_path):
    from core import watcher as w
    instances = _install_fake_watchdog(monkeypatch, w)
    got = []
    fw = w.FolderWatcher(str(tmp_path), got.append)
    fw.start()

    handler = instances[-1].handler
    created = str(tmp_path / "new.wav")
    handler.on_created(_Event(src_path=created))

    assert got == [created]
    fw.stop()


def test_folder_watcher_moved_callback_error_hits_on_error(monkeypatch, tmp_path):
    """The Audit A8 error hook must fire for moved events too."""
    from core import watcher as w
    instances = _install_fake_watchdog(monkeypatch, w)

    def boom(_path):
        raise RuntimeError("enqueue failed")

    errors = []
    fw = w.FolderWatcher(
        str(tmp_path), boom, on_error=lambda path, exc: errors.append((path, exc))
    )
    fw.start()

    handler = instances[-1].handler
    dest = str(tmp_path / "clip.mkv")
    handler.on_moved(_Event(dest_path=dest))

    assert len(errors) == 1
    assert errors[0][0] == dest
    assert isinstance(errors[0][1], RuntimeError)
    fw.stop()
