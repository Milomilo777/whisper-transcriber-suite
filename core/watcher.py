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
import re
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


_MEDIA_EXTENSIONS = {
    ".mp3", ".mp4", ".wav", ".m4a", ".mkv", ".webm", ".flac",
    ".ogg", ".aac", ".aiff", ".opus", ".mov",
    # Formats ffmpeg reads that the watcher and folder drops used to skip
    # without a word: broadcast / camcorder / DVD video, Windows Media,
    # older containers.
    ".ts", ".m2ts", ".mts", ".vob", ".wmv", ".wma", ".avi", ".m4v",
    ".3gp", ".flv", ".mpg", ".mpeg", ".mka",
}

# MPEG transport streams start every 188-byte packet with this sync byte.
_TS_SYNC_BYTE = b"\x47"

# yt-dlp downloads the video and audio of a merged format as "name.f137.mp4"
# and "name.f251.webm" (format ids like 137, 251-drc, hls-1080p, dash-720p)
# and post-processes into "name.temp.mp4"; the finished file arrives later
# under its own name.
_YTDLP_PART_RE = re.compile(
    r"\.(?:f(?:\d{2,}(?:-[\w-]+)?|(?:hls|dash|http)-[\w-]+)|temp)\.[^.]+$", re.IGNORECASE
)


def is_download_intermediate(path: str) -> bool:
    """True for a yt-dlp part file that is not the finished download."""
    return bool(_YTDLP_PART_RE.search(os.path.basename(path)))


def is_media_file(path: str) -> bool:
    """True when ``path``'s extension is one of the watched media types.

    Shared with the app's drag-and-drop folder handling so "what counts
    as a media file" stays defined in exactly one place. A ``.ts`` file is
    also a TypeScript source file: one that can be read and does not start
    with the MPEG-TS sync byte is not media (an empty or unreadable one,
    e.g. still being copied, gets the benefit of the doubt).
    """
    ext = os.path.splitext(path)[1].lower()
    if ext not in _MEDIA_EXTENSIONS:
        return False
    if os.path.basename(path).startswith("._"):
        # macOS AppleDouble metadata ("._clip.mp4") written next to every
        # file copied to a FAT/exFAT/network drive: never media.
        return False
    if ext == ".ts":
        try:
            with open(path, "rb") as f:
                first = f.read(1)
        except OSError:
            return True
        return first in (b"", _TS_SYNC_BYTE)
    return True


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
        folder = self.folder

        class _Handler(FileSystemEventHandler):
            def _dispatch(self, path: bytes | str) -> None:
                if isinstance(path, bytes):
                    path = path.decode("utf-8", "replace")
                if not path or not is_media_file(path):
                    return
                if is_download_intermediate(path):
                    logger.info("Watched folder: skipped %s (a yt-dlp part file)", path)
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
