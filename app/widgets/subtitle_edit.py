"""GUI side of the "Open in Subtitle Edit" button (Windows only).

Detection, the command line and the process start live in :mod:`core.subtitle_edit`; this
module adds the dialogs: an error when the file or program cannot be opened, and, when
Subtitle Edit is not installed, an offer to open the official download page.
"""
from __future__ import annotations

import tkinter as tk
import webbrowser
from collections.abc import Mapping
from tkinter import messagebox
from typing import Any

from app.widgets.error_dialog import show_error
from core import subtitle_edit

BUTTON_TEXT = "Open in Subtitle Edit"
HELP_TEXT = (
    "Opens the subtitle file in Subtitle Edit, a free editor with a waveform view for "
    "fine-tuning timing. If it is not installed, this button offers the download page. "
    "A portable copy can be chosen in Advanced > App behaviour."
)


def open_in_subtitle_edit(
    parent: tk.Misc, config: Mapping[str, Any] | None, subtitle_path: str | None,
) -> None:
    """Open ``subtitle_path`` in Subtitle Edit, or explain what is missing."""
    exe = subtitle_edit.find_subtitle_edit(str((config or {}).get(subtitle_edit.CONFIG_KEY) or ""))
    if exe is None:
        if messagebox.askyesno(
            "Subtitle Edit not found",
            "Subtitle Edit was not found on this computer.\n\n"
            "It is a free subtitle editor. Open its official download page now?\n\n"
            "If you already have a portable copy, choose SubtitleEdit.exe in "
            "Advanced > App behaviour.",
            parent=parent,
        ):
            webbrowser.open(subtitle_edit.DOWNLOAD_URL)
        return
    if not subtitle_path:
        messagebox.showwarning(
            "No subtitle file",
            "There is no subtitle file (SRT, VTT, ASS) for this transcript yet.",
            parent=parent,
        )
        return
    try:
        subtitle_edit.open_in_subtitle_edit(exe, subtitle_path)
    except FileNotFoundError:
        messagebox.showwarning(
            "Subtitle file missing",
            f"The subtitle file is no longer there:\n{subtitle_path}",
            parent=parent,
        )
    except OSError as e:
        top = parent.winfo_toplevel()
        if isinstance(top, (tk.Tk, tk.Toplevel)):
            show_error(top, "Open failed", "Could not start Subtitle Edit.", detail=str(e))
        else:
            messagebox.showerror("Open failed", str(e), parent=parent)
