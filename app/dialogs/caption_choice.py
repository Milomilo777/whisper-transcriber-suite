"""The question before a download that would be transcribed: use the subtitles or transcribe?

Shown by ``DownloadService.enqueue_from_form`` only when the video already has subtitles in the
chosen language and "Transcribe after download" is on. Subtitles take seconds; a transcription
takes minutes. "Don't ask again" remembers the answer in ``download_caption_choice`` (see
``core.config``); Advanced settings > Downloads changes it back to asking.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.dpi import place_over, px
from app.i18n import _
from app.theme import tokens

CHOICE_ASK = "ask"
CHOICE_CAPTIONS = "captions"
CHOICE_TRANSCRIBE = "transcribe"
CHOICE_CANCEL = "cancel"
REMEMBERED_CHOICES = (CHOICE_CAPTIONS, CHOICE_TRANSCRIBE)


def remembered_choice(config: dict) -> str:
    """The saved "don't ask again" answer, or ``"ask"`` for anything else."""
    value = str(config.get("download_caption_choice") or CHOICE_ASK)
    return value if value in REMEMBERED_CHOICES else CHOICE_ASK


def ask_caption_choice(master: "tk.Misc", *, kind: str, language: str) -> tuple[str, bool]:
    """Modal question; returns ``(choice, dont_ask_again)``.

    ``choice`` is ``"captions"``, ``"transcribe"`` or ``"cancel"`` (window closed).
    ``kind`` is ``"manual"`` or ``"auto"``, ``language`` the name shown to the user.
    """
    dialog = tk.Toplevel(master)
    dialog.title(_("This video already has subtitles"))
    dialog.transient(master)  # type: ignore[arg-type]
    dialog.resizable(False, False)
    result = {"choice": CHOICE_CANCEL}
    dont_ask = tk.BooleanVar(master=dialog, value=False)

    def pick(choice: str) -> None:
        result["choice"] = choice
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(
        body, text=_("Use the subtitles (ready in seconds) or transcribe the video (takes minutes)?"),
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w")
    if kind == "manual":
        note = _("This video has {language} subtitles made by the uploader. Using them gives "
                 "you a subtitle file only; the video itself is not downloaded.", language=language)
    else:
        note = _("This video has automatic {language} subtitles, which can be less accurate "
                 "than a transcription. Using them gives you a subtitle file only; the video "
                 "itself is not downloaded.", language=language)
    ttk.Label(body, text=note, foreground=tokens.themed(tokens.TEXT_MUTED), wraplength=px(440), justify="left").pack(
        anchor="w", pady=(6, 10)
    )
    ttk.Checkbutton(
        body, text=_("Don't ask again (to undo: Advanced settings on the Transcribe tab)"), variable=dont_ask,
    ).pack(anchor="w")
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(12, 0))
    transcribe = ttk.Button(
        actions, text=_("Transcribe"), style="Accent.TButton",
        command=lambda: pick(CHOICE_TRANSCRIBE),
    )
    transcribe.pack(side="right")
    ttk.Button(
        actions, text=_("Use the subtitles"), command=lambda: pick(CHOICE_CAPTIONS),
    ).pack(side="right", padx=(0, 8))
    # A visible way out: before, only the window's X cancelled (code review, 2026-10-21).
    ttk.Button(actions, text=_("Cancel"), command=lambda: pick(CHOICE_CANCEL)).pack(side="left")
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(CHOICE_CANCEL))
    dialog.bind("<Escape>", lambda _e: pick(CHOICE_CANCEL))  # as the close button
    def on_return(event: "tk.Event[tk.Misc]") -> None:
        # Enter presses the focused button (Tab moves focus); else Transcribe. Before,
        # neither key did anything (click-through test, 2026-10-21).
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            pick(CHOICE_TRANSCRIBE)

    dialog.bind("<Return>", on_return)
    place_over(dialog, master)
    dialog.update_idletasks()
    transcribe.focus_set()
    try:
        dialog.grab_set()
    except tk.TclError:
        pass  # headless test runs cannot always grab
    master.wait_window(dialog)
    return result["choice"], bool(dont_ask.get()) and result["choice"] != CHOICE_CANCEL
