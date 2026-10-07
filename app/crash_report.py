"""Last-resort reporting for errors nothing else catches in the GUI process.

The installed app runs under pythonw, where ``sys.stderr`` is ``None``: Python's default
``sys.excepthook`` prints the traceback there, so a crash while the main window is being
built (an exception out of ``App.__init__``) left no trace and no message at all. The hook
installed here writes the traceback to the app log and shows the user a short message
that says where the details are. Errors inside Tk callbacks are handled separately by
``App.report_callback_exception``.
"""
from __future__ import annotations

import logging
import sys
from types import TracebackType
from typing import Callable

logger = logging.getLogger(__name__)

_TITLE = "Whisper Transcriber Suite"


def _ensure_log_file() -> None:
    """The crash can come before ``App.__init__`` set up logging: open the log now."""
    if logging.getLogger().handlers:
        return
    try:
        from core import logging_setup
        logging_setup.setup_logging()
    except Exception:  # noqa: BLE001 - reporting the original error matters more
        pass


def _log_folder() -> str:
    try:
        from core.config import user_log_dir
        return str(user_log_dir())
    except Exception:  # noqa: BLE001
        return "the app's log folder"


def show_error_box(message: str) -> None:
    """A message box on a fresh, hidden Tk root (the app's own may be half-built)."""
    import tkinter as tk
    from tkinter import messagebox

    root = tk.Tk()
    try:
        root.withdraw()
        messagebox.showerror(_TITLE, message, parent=root)
    finally:
        root.destroy()


def install_excepthook(notify: Callable[[str], None] | None = None) -> None:
    """Route uncaught main-thread exceptions to the app log and tell the user.

    ``notify`` shows the message (a Tk message box by default). The previous hook still
    runs afterwards, so a console run keeps printing the traceback.
    """
    previous = sys.excepthook
    show = notify or show_error_box

    def _hook(
        exc_type: type[BaseException], exc: BaseException, tb: TracebackType | None
    ) -> None:
        if not issubclass(exc_type, KeyboardInterrupt):
            _ensure_log_file()
            logger.critical("The app stopped because of an unhandled error",
                            exc_info=(exc_type, exc, tb))
            try:
                show(
                    "The app stopped because of an unexpected error:\n\n"
                    f"{exc_type.__name__}: {exc}\n\n"
                    f"The details are in app.log in {_log_folder()}."
                )
            except Exception:  # noqa: BLE001 - e.g. no display; the log has it
                logger.debug("Could not show the crash message", exc_info=True)
        previous(exc_type, exc, tb)

    sys.excepthook = _hook
