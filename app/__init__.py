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


def run() -> None:
    """Launch the Tk app. Used by ``gui.py`` and the frozen exe entry point."""
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
    from .app import App
    App().mainloop()


def __getattr__(name: str):
    if name == "App":
        from .app import App as _App
        return _App
    raise AttributeError(name)
