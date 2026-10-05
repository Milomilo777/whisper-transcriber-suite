"""The quiet "new version available" bar and its two small windows.

The bar sits between the menu and the tabs. It never takes focus, never grabs
input and never opens a window by itself: the user reads it when they like and
answers with What's new / Download / Later / Skip this version. The rules for
when it may appear live in ``core.updates`` (pure, tested without Tk); the app
glue is ``App._on_update_result`` and the ``App._update_*`` handlers.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable

_WRAP_MIN = 220
_WINDOW_WRAP = 460


class UpdateBar(ttk.Frame):
    """A one-line notice with four buttons, gridded in and out by pack."""

    BUTTONS = (
        ("whats_new", "What's new"),
        ("download", "Download"),
        ("later", "Later"),
        ("skip", "Skip this version"),
    )

    def __init__(
        self,
        master: tk.Misc,
        *,
        on_whats_new: Callable[[], None],
        on_download: Callable[[], None],
        on_later: Callable[[], None],
        on_skip: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=(10, 6, 10, 0))
        self.text_var = tk.StringVar(master=self, value="")
        row = ttk.Frame(self)
        row.pack(fill="x")
        self.label = ttk.Label(row, textvariable=self.text_var, anchor="w", justify="left")
        self.label.pack(side="left", fill="x", expand=True)
        self._button_row = ttk.Frame(row)
        self._button_row.pack(side="right")
        commands = {
            "whats_new": on_whats_new,
            "download": on_download,
            "later": on_later,
            "skip": on_skip,
        }
        self.buttons: dict[str, ttk.Button] = {}
        for key, text in self.BUTTONS:
            button = ttk.Button(self._button_row, text=text, command=commands[key])
            button.pack(side="left", padx=(6, 0))
            self.buttons[key] = button
        ttk.Separator(self, orient="horizontal").pack(fill="x", pady=(6, 0))
        self.bind("<Configure>", self._rewrap, add="+")

    def _rewrap(self, event: "tk.Event[tk.Misc]") -> None:
        room = int(event.width) - self._button_row.winfo_reqwidth() - 40
        self.label.configure(wraplength=max(_WRAP_MIN, room))

    @property
    def visible(self) -> bool:
        return bool(self.winfo_manager())

    def show(self, text: str, *, before: tk.Misc) -> None:
        """Show ``text`` above ``before`` (the tabs). Never moves the focus."""
        self.text_var.set(text)
        if not self.visible:
            self.pack(side="top", fill="x", before=before)

    def hide(self) -> None:
        if self.visible:
            self.pack_forget()


def _window(parent: tk.Misc, title: str) -> tuple[tk.Toplevel, ttk.Frame]:
    top = tk.Toplevel(parent)
    top.title(title)
    if isinstance(parent, (tk.Tk, tk.Toplevel)):
        top.transient(parent)
    top.resizable(False, False)
    frame = ttk.Frame(top, padding=14)
    frame.pack(fill="both", expand=True)
    top.bind("<Escape>", lambda _e: top.destroy())
    return top, frame


def show_whats_new(
    parent: tk.Misc,
    *,
    version: str,
    headline: str,
    highlights: tuple[str, ...],
    on_full_notes: Callable[[], object],
) -> tk.Toplevel:
    """A small, non-modal window with the release's headline and highlights."""
    top, frame = _window(parent, f"What's new in {version}")
    if headline:
        ttk.Label(
            frame, text=headline, wraplength=_WINDOW_WRAP, justify="left",
            font=("TkDefaultFont", 10, "bold"),
        ).pack(anchor="w")
    for line in highlights:
        ttk.Label(
            frame, text="• " + line, wraplength=_WINDOW_WRAP, justify="left",
        ).pack(anchor="w", pady=(8, 0))
    if not headline and not highlights:
        ttk.Label(
            frame, text="This release has no short summary. The full notes have the details.",
            wraplength=_WINDOW_WRAP, justify="left",
        ).pack(anchor="w")
    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(14, 0))
    ttk.Button(buttons, text="Full release notes", command=on_full_notes).pack(side="left")
    ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")
    return top


def show_update_command(parent: tk.Misc, *, version: str, command: str) -> tk.Toplevel:
    """A small window with the command that updates a source checkout."""
    top, frame = _window(parent, f"Update to {version}")
    ttk.Label(
        frame,
        text=(
            f"Version {version} is available. This copy runs from the source code; "
            "to update it, close the app and run this command in a terminal:"
        ),
        wraplength=_WINDOW_WRAP, justify="left",
    ).pack(anchor="w")
    # The text is inserted, not bound to a StringVar: a variable owned only by
    # this function is garbage-collected on return and the field goes blank.
    entry = ttk.Entry(frame, width=64)
    entry.insert(0, command)
    entry.configure(state="readonly")
    entry.pack(fill="x", pady=(8, 0))
    status = tk.StringVar(master=top, value="")

    def _copy() -> None:
        top.clipboard_clear()
        top.clipboard_append(command)
        status.set("Copied.")

    buttons = ttk.Frame(frame)
    buttons.pack(fill="x", pady=(10, 0))
    ttk.Button(buttons, text="Copy", command=_copy).pack(side="left")
    ttk.Label(buttons, textvariable=status).pack(side="left", padx=(8, 0))
    ttk.Button(buttons, text="Close", command=top.destroy).pack(side="right")
    return top
