"""oTranscribe (and future integrations) wiring."""
from __future__ import annotations

import logging
import os
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING

from app.domain.task_outputs import task_srt_output
from app.i18n import _
from app.widgets.error_dialog import show_error
from core import convert
from core.integrations.otranscribe import otr_to_srt, srt_to_otr

if TYPE_CHECKING:
    from app.app import App
    from core.task import TranscriptionTask

logger = logging.getLogger(__name__)


def _write_text_atomic(path: str, text: str) -> None:
    """Write UTF-8 with LF line ends via a temp sibling + os.replace.

    A failed write leaves any existing file untouched instead of a
    truncated one; LF matches every other writer on every OS.
    """
    convert._replace_atomically(path, text.encode("utf-8"))


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
                _("Cannot export"),
                _("This task has no SRT file on disk — add SRT to the output "
                  "formats and run it again."),
                parent=self.app,
            )
            return
        # Beside the SRT the run really wrote ("name (1).otr" for a re-run).
        otr_path = os.path.splitext(srt_path)[0] + ".otr"
        replace = False
        if os.path.exists(otr_path):
            # The user may have edited this file in oTranscribe; never
            # replace it without asking.
            choice = messagebox.askyesnocancel(
                _("Replace .otr file?"),
                _("{name} already exists and may hold "
                  "your oTranscribe edits.\n\nYes: replace it\n"
                  "No: keep it and save a new file\nCancel: do nothing",
                  name=os.path.basename(otr_path)),
                parent=self.app,
                default="cancel",
            )
            if choice is None:
                return
            replace = bool(choice)
        try:
            payload = srt_to_otr(srt_path, os.path.basename(task.file_path))
            if replace:
                _write_text_atomic(otr_path, payload)
            else:
                otr_path = convert._publish_new_output(otr_path, payload.encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            logger.exception("Export to .otr failed")
            show_error(
                self.app, _("Export failed"),
                _("Could not create the oTranscribe (.otr) file."), detail=str(e),
            )
            return
        self.app.log(f"Saved {otr_path}")
        self.app.status_var.set(_("Saved {name}", name=os.path.basename(otr_path)))

    def import_otr_to_srt(self) -> None:
        otr_path = filedialog.askopenfilename(
            title=_("Choose an .otr file"),
            filetypes=[(_("oTranscribe files"), "*.otr"), (_("All files"), "*.*")],
            parent=self.app,
        )
        if not otr_path:
            return
        suggested = Path(otr_path).with_suffix(".srt").name
        srt_path = filedialog.asksaveasfilename(
            title=_("Save SRT as..."),
            defaultextension=".srt",
            initialfile=suggested,
            filetypes=[(_("SubRip subtitle"), "*.srt"), (_("All files"), "*.*")],
            parent=self.app,
        )
        if not srt_path:
            return
        try:
            text = otr_to_srt(otr_path)
            if convert._same_file(srt_path, otr_path):
                # A mistaken Save As selection must not destroy the import.
                srt_path = convert._publish_new_output(
                    str(Path(srt_path).with_suffix(".converted.srt")), text.encode("utf-8"),
                )
            else:
                _write_text_atomic(srt_path, text)
        except Exception as e:  # noqa: BLE001
            logger.exception("Import .otr → SRT failed")
            show_error(
                self.app, _("Import failed"),
                _("Could not convert that .otr file to SRT."), detail=str(e),
            )
            return
        self.app.log(f"Wrote {srt_path}")
        self.app.status_var.set(_("Saved {name}", name=os.path.basename(srt_path)))
