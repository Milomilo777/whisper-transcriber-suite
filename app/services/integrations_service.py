"""oTranscribe (and future integrations) wiring."""
from __future__ import annotations

import logging
import os
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

from app.domain.task_outputs import task_srt_output
from app.widgets.error_dialog import show_error
from core.integrations.otranscribe import otr_to_srt, srt_to_otr

if TYPE_CHECKING:
    from app.app import App
    from core.task import TranscriptionTask

logger = logging.getLogger(__name__)


def _free_path(path: str) -> str:
    """``name (1).ext``, ``name (2).ext``, ... — the first name not on disk."""
    root, ext = os.path.splitext(path)
    n = 1
    while os.path.exists(f"{root} ({n}){ext}"):
        n += 1
    return f"{root} ({n}){ext}"


def _write_text_atomic(path: str, text: str) -> None:
    """Write UTF-8 with LF line ends via a temp sibling + os.replace.

    A failed write leaves any existing file untouched instead of a
    truncated one; LF matches every other writer on every OS.
    """
    tmp = f"{path}.{os.getpid()}.part"
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class IntegrationsService:
    def __init__(self, app: "App") -> None:
        self.app = app

    def open_otranscribe(self) -> None:
        webbrowser.open("https://otranscribe.com/")
        self.app.log(
            "Opened https://otranscribe.com/ in your browser. "
            "Drag the audio and the .otr file into the page."
        )

    def export_task_to_otr(self, task: "TranscriptionTask") -> None:
        srt_path = task_srt_output(task)
        if srt_path is None:
            messagebox.showwarning(
                "Cannot export",
                "This task has no SRT file on disk — add SRT to the output "
                "formats and run it again.",
                parent=self.app,
            )
            return
        # Beside the SRT the run really wrote ("name (1).otr" for a re-run).
        otr_path = os.path.splitext(srt_path)[0] + ".otr"
        if os.path.exists(otr_path):
            # The user may have edited this file in oTranscribe; never
            # replace it without asking.
            choice = messagebox.askyesnocancel(
                "Replace .otr file?",
                f"{os.path.basename(otr_path)} already exists and may hold "
                "your oTranscribe edits.\n\nYes: replace it\n"
                "No: keep it and save a new file\nCancel: do nothing",
                parent=self.app,
            )
            if choice is None:
                return
            if not choice:
                otr_path = _free_path(otr_path)
        try:
            payload = srt_to_otr(srt_path, os.path.basename(task.file_path))
            _write_text_atomic(otr_path, payload)
        except Exception as e:  # noqa: BLE001
            logger.exception("Export to .otr failed")
            show_error(
                self.app, "Export failed",
                "Could not create the oTranscribe (.otr) file.", detail=str(e),
            )
            return
        self.app.log(f"Saved {otr_path}")
        self.app.status_var.set(f"Saved {os.path.basename(otr_path)}")

    def import_otr_to_srt(self) -> None:
        otr_path = filedialog.askopenfilename(
            title="Choose an .otr file",
            filetypes=[("oTranscribe files", "*.otr"), ("All files", "*.*")],
            parent=self.app,
        )
        if not otr_path:
            return
        suggested = Path(otr_path).with_suffix(".srt").name
        srt_path = filedialog.asksaveasfilename(
            title="Save SRT as...",
            defaultextension=".srt",
            initialfile=suggested,
            filetypes=[("SubRip subtitle", "*.srt"), ("All files", "*.*")],
            parent=self.app,
        )
        if not srt_path:
            return
        try:
            text = otr_to_srt(otr_path)
            _write_text_atomic(srt_path, text)
        except Exception as e:  # noqa: BLE001
            logger.exception("Import .otr → SRT failed")
            show_error(
                self.app, "Import failed",
                "Could not convert that .otr file to SRT.", detail=str(e),
            )
            return
        self.app.log(f"Wrote {srt_path}")
        self.app.status_var.set(f"Saved {os.path.basename(srt_path)}")
