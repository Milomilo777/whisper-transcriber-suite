"""The question when an English-only model meets speech in another language.

An English-only Whisper model (``tiny.en``, the distilled models, ...) cannot
transcribe anything but English: Persian speech comes out as made-up English
words or a rough English translation, with no error anywhere. faster-whisper
only logs a warning, which is easy to miss. This dialog says what is wrong,
which model to use instead and why, and switches with one click.

Shown by the Live tab (on Start and when its language or model changes) and
by the Transcribe tab before a file is queued.
"""
from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from tkinter import ttk

from app.dpi import place_over, px
from app.i18n import _
from app.theme import tokens

CHOICE_SWITCH = "switch"
CHOICE_CHOOSE = "choose"
CHOICE_KEEP = "keep"
CHOICE_CANCEL = "cancel"


@dataclass(frozen=True)
class EnglishOnlyPrompt:
    """What the dialog says; built by the caller, which knows the context."""

    model: str  # the English-only model, as the user knows it (its slug)
    language: str  # the language's display name; "" for auto-detect
    alternative: str  # the model to switch to (its slug)
    reason: str  # one line on why the alternative fits
    size_text: str = ""  # e.g. "about 500 MB"; "" when unknown
    downloaded: bool = False

    def headline(self) -> str:
        return _("{model} understands English only.", model=self.model)

    def problem(self) -> str:
        if self.language:
            return _("{language} speech will come out as wrong English text: made-up words or "
                     "a rough English translation, not what was said.", language=self.language)
        return _("With Auto, any speech that is not English will come out as wrong English "
                 "text: made-up words or a rough English translation, not what was said.")

    def recommendation(self) -> str:
        if self.downloaded:
            status = _("Already on this computer.")
        elif self.size_text:
            status = _("Needs a one-time download ({size}).", size=self.size_text)
        else:
            status = _("Needs a one-time download.")
        # Three whole sentences: the pick, the caller's reason, and the download status.
        return _("Recommended: {model}. {reason} {status}", model=self.alternative,
                 reason=self.reason, status=status)


def _centre_over(dialog: tk.Toplevel, master: "tk.Misc") -> None:
    """Put ``dialog`` over the middle of ``master``'s window, if that is shown."""
    if sys.platform == "win32":
        place_over(dialog, master)
        return
    try:
        top = master.winfo_toplevel()
        if not top.winfo_ismapped():
            return
        x = top.winfo_rootx() + (top.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - dialog.winfo_reqheight()) // 3
        # No clamp to 0: a monitor left of or above the primary one has
        # negative coordinates, and Tk accepts "+-800+40".
        dialog.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass


def ask_english_only(master: "tk.Misc", prompt: EnglishOnlyPrompt) -> str:
    """Modal question; returns one of the ``CHOICE_*`` values.

    "Switch" is the default button (Enter); Escape or closing the window
    is Cancel. Nothing is changed here: the caller acts on the answer.
    """
    dialog = tk.Toplevel(master)
    dialog.title(_("This model understands English only"))
    dialog.transient(master)  # type: ignore[arg-type]
    dialog.resizable(False, False)
    result = {"choice": CHOICE_CANCEL}

    def pick(choice: str) -> None:
        result["choice"] = choice
        dialog.destroy()

    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    ttk.Label(
        body, text=prompt.headline(), font=("TkDefaultFont", 10, "bold"),
        wraplength=px(460), justify="left",
    ).pack(anchor="w")
    ttk.Label(
        body, text=prompt.problem(), wraplength=px(460), justify="left",
    ).pack(anchor="w", pady=(6, 0))
    ttk.Label(
        body, text=prompt.recommendation(), wraplength=px(460), justify="left",
        foreground=tokens.themed(tokens.TEXT_MUTED),
    ).pack(anchor="w", pady=(8, 0))

    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(14, 0))
    switch = ttk.Button(
        actions, text=_("Switch to {model}", model=prompt.alternative), style="Accent.TButton",
        command=lambda: pick(CHOICE_SWITCH),
    )
    switch.pack(side="left")
    ttk.Button(
        actions, text=_("Choose another model…"),
        command=lambda: pick(CHOICE_CHOOSE),
    ).pack(side="left", padx=(8, 0))
    more = ttk.Frame(body)
    more.pack(fill="x", pady=(8, 0))
    ttk.Button(
        more, text=_("Keep {model} anyway", model=prompt.model),
        command=lambda: pick(CHOICE_KEEP),
    ).pack(side="left")
    ttk.Button(
        more, text=_("Cancel"), command=lambda: pick(CHOICE_CANCEL),
    ).pack(side="right")

    dialog.protocol("WM_DELETE_WINDOW", lambda: pick(CHOICE_CANCEL))
    dialog.bind("<Escape>", lambda _e: pick(CHOICE_CANCEL))
    def on_return(event: "tk.Event[tk.Misc]") -> None:
        # Enter presses the focused button (Tab moves focus); else Switch.
        if isinstance(event.widget, ttk.Button):
            event.widget.invoke()
        else:
            pick(CHOICE_SWITCH)

    dialog.bind("<Return>", on_return)
    dialog.update_idletasks()
    _centre_over(dialog, master)
    switch.focus_set()
    try:
        dialog.grab_set()
    except tk.TclError:
        pass  # headless test runs cannot always grab
    master.wait_window(dialog)
    return result["choice"]
