"""Watched folder integration.

When the user configures a folder under ``app_config["watched_folder"]``
and toggles ``watched_folder_enabled`` on, any media file dropped
into that folder is enqueued for transcription automatically.

Wraps ``watchdog`` lazily so the import doesn't fail when the
wheel isn't installed (the UI checkbox stays disabled with a
clear "unavailable" label in that case).
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


_MEDIA_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".m4a", ".mkv", ".webm", ".flac",
    ".ogg", ".aac", ".aiff", ".opus", ".mov",
}


def is_media_file(path: str) -> bool:
    """True when ``path``'s extension is one of the watched media types.

    Shared with the app's drag-and-drop folder handling so "what counts
    as a media file" stays defined in exactly one place.
    """
    return os.path.splitext(path)[1].lower() in _MEDIA_EXTENSIONS


def _is_inside(folder: str, path: bytes | str) -> bool:
    """True when ``path`` resolves to a location inside ``folder``.

    Used to filter ``on_moved`` events: some watchdog backends also report
    a move OUT of the watched folder (source inside, destination outside),
    and enqueueing a file that just left the folder would be wrong.
    """
    if isinstance(path, bytes):
        path = path.decode("utf-8", "replace")
    if not path:
        return False
    try:
        rel = os.path.relpath(os.path.abspath(path), os.path.abspath(folder))
    except (OSError, ValueError):  # e.g. different drive on Windows
        return False
    return rel != os.pardir and not rel.startswith(os.pardir + os.sep)


def is_available() -> bool:
    try:
        import watchdog  # type: ignore[import-untyped] # noqa: F401
    except ImportError:
        return False
    return True


def availability_reason() -> str:
    if is_available():
        return ""
    return "watchdog Python package not installed"


class FolderWatcher:
    """One-folder daemon watcher.

    Pass an ``on_new_file(path)`` callback that the App's main
    thread will receive via the existing event queue. The callback
    is invoked from a watchdog worker thread, so callers must
    push to a Tk-safe queue rather than touch widgets directly.
    """

    def __init__(
        self,
        folder: str,
        on_new_file: Callable[[str], None],
        *,
        on_error: Callable[[str, BaseException], None] | None = None,
    ) -> None:
        """``on_error(path, exc)`` is invoked when ``on_new_file``
        raises. Audit A8: without this hook a failing enqueue
        silently dropped the file. Default is None (log only) so
        existing callers keep working unchanged."""
        self.folder = folder
        self.on_new_file = on_new_file
        self.on_error = on_error
        self._observer: Any = None
        # RLock — start() calls self.stop() inside its critical section
        # to tear down a prior observer. With a plain Lock that re-acquire
        # deadlocks; RLock lets the same thread re-enter.
        self._lock = threading.RLock()

    def start(self) -> None:
        if not is_available():
            raise RuntimeError(availability_reason())
        from watchdog.events import FileSystemEventHandler  # type: ignore[import-untyped]
        from watchdog.observers import Observer  # type: ignore[import-untyped]

        cb = self.on_new_file
        err_cb = self.on_error
        media_exts = _MEDIA_EXTENSIONS
        folder = self.folder

        class _Handler(FileSystemEventHandler):
            def _dispatch(self, path: bytes | str) -> None:
                if isinstance(path, bytes):
                    path = path.decode("utf-8", "replace")
                if not path or os.path.splitext(path)[1].lower() not in media_exts:
                    return
                try:
                    cb(path)
                except Exception as e:  # noqa: BLE001
                    logger.exception("Watcher callback raised on %s", path)
                    # Audit A8: surface to the App so the user sees
                    # "watcher dropped X.mp3" instead of silent loss.
                    if err_cb is not None:
                        try:
                            err_cb(path, e)
                        except Exception:  # noqa: BLE001
                            logger.exception(
                                "Watcher on_error hook itself raised "
                                "(path=%s)", path,
                            )

            def on_created(self, event):  # noqa: N805
                if event.is_directory:
                    return
                self._dispatch(event.src_path)

            def on_moved(self, event):  # noqa: N805
                # A file dragged into the folder — or a downloader's
                # ".part" -> final-name rename — arrives as a MOVED event,
                # not a create (Windows FILE_ACTION_RENAMED_NEW_NAME;
                # Linux IN_MOVED_TO). Handling only on_created meant the
                # headline "drop a media file here" flow silently did
                # nothing for a same-volume move (Explorer's default drag).
                if event.is_directory:
                    return
                dest = getattr(event, "dest_path", "")
                if _is_inside(folder, dest):
                    self._dispatch(dest)

        with self._lock:
            self.stop()
            observer = Observer()
            observer.schedule(_Handler(), self.folder, recursive=False)
            observer.daemon = True
            observer.start()
            self._observer = observer
            logger.info("FolderWatcher started for %s", self.folder)

    def stop(self) -> None:
        with self._lock:
            obs = self._observer
            self._observer = None
        if obs is None:
            return
        try:
            obs.stop()
            obs.join(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        logger.info("FolderWatcher stopped")

    def is_running(self) -> bool:
        with self._lock:
            obs = self._observer
        return obs is not None and getattr(obs, "is_alive", lambda: False)()
