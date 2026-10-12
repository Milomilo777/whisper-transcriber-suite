"""Whisper Transcriber Suite — Tk desktop app.

Layout:
    app.app                 — the App class (Tk root, wires services)
    app.dialogs             — Toplevel dialogs (model download, etc.)
    app.domain              — task models and enumerations
    app.services            — background work (downloads, transcription, formats)
    app.widgets             — small custom widgets

Public entry point: ``app.run()``.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # Re-exported lazily by ``__getattr__`` so importing this package
    # does not pull in tkinter / faster-whisper until ``app.App`` is
    # actually requested. The TYPE_CHECKING block keeps the name
    # visible to static analysers and IDE autocomplete.
    from .app import App as App  # noqa: F401

__all__ = ["run", "App"]


def run(open_paths: list[str] | None = None) -> None:
    """Launch the Tk app. Used by ``gui.py`` and the frozen exe entry point.

    ``open_paths``: files from the command line (a file dropped on the
    shortcut), handled like files dropped on the window.
    """
    # Before the Tk root exists, or Windows stretches the window and blurs it.
    from .dpi import enable_dpi_awareness
    enable_dpi_awareness()
    # Work offline backstop for this process; inert while the switch is off.
    from core import offline
    offline.install_network_guard()
    # Before App(): under pythonw a crash while the window is built would
    # otherwise leave no trace and no message.
    from . import crash_report
    crash_report.install_excepthook()
    # The interface language, before any module that builds widget text is imported. The
    # config is read without the online layer: no network request before the window opens.
    from core.config import load_config
    from . import i18n
    i18n.init_language(lambda: load_config(fetch_online=False))
    from .app import App
    app = App()
    if open_paths:
        paths = list(open_paths)
        app.after_idle(lambda: app.open_paths(paths))
    app.mainloop()


def __getattr__(name: str):
    if name == "App":
        from .app import App as _App
        return _App
    raise AttributeError(name)
