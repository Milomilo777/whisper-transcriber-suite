"""The question before a download that would be transcribed: use the subtitles or transcribe?

Shown by ``DownloadService.enqueue_from_form`` only when the video already has subtitles in the
chosen language and "Transcribe after download" is on. Subtitles take seconds; a transcription
takes minutes. "Don't ask again" remembers the answer in ``download_caption_choice`` (see
``core.config``); Advanced settings > Downloads changes it back to asking.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

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
    dialog.title("Subtitles already exist")
    dialog.transient(master)  # type: ignore[arg-type]
    dialog.resizable(False, False)
    result = {"choice": CHOICE_CANCEL}
    dont_ask = tk.BooleanVar(master=dialog, value=False)

    def pick(choice: str) -> None:
        result["choice"] = choice
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    origin = "made by the uploader" if kind == "manual" else "automatic"
    ttk.Label(
        body, text="Use the existing subtitles (seconds) or transcribe (minutes)?",
        font=("TkDefaultFont", 10, "bold"),
    ).pack(anchor="w")
    note = f"This video has {language} subtitles ({origin})."
    if kind != "manual":
        note += " Automatic subtitles can be less accurate than a transcription."
    note += " Using the subtitles saves no video or audio file."
    ttk.Label(body, text=note, foreground="#666", wraplength=440, justify="left").pack(
        anchor="w", pady=(6, 10)
    )
    ttk.Checkbutton(body, text="Don't ask again", variable=dont_ask).pack(anchor="w")
    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(12, 0))
    ttk.Button(
        actions, text="Transcribe", style="Accent.TButton",
        command=lambda: pick(CHOICE_TRANSCRIBE),
    ).pack(side="right")
    ttk.Button(
        actions, text="Use the subtitles", command=lambda: pick(CHOICE_CAPTIONS),
    ).pack(side="right", padx=(0, 8))
    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(CHOICE_CANCEL))
    dialog.update_idletasks()
    try:
        dialog.grab_set()
    except tk.TclError:
        pass  # headless test runs cannot always grab
    master.wait_window(dialog)
    return result["choice"], bool(dont_ask.get()) and result["choice"] != CHOICE_CANCEL
