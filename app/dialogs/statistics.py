"""Statistics dialog (Phase 3a).

A read-only summary of the SQLite history. Opened from File → Statistics....
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

from app.widgets.error_dialog import show_error

if TYPE_CHECKING:
    from app.app import App


def show_statistics(app: "App") -> None:
    if not app.history:
        messagebox.showinfo("Statistics", "history.db is unavailable.", parent=app)
        return
    try:
        s = app.history.stats()
    except Exception as e:  # noqa: BLE001
        # A locked / unreadable history.db (I/O error, another process
        # holding the file) would otherwise raise inside the menu callback,
        # which Tk reports only to stderr — the user sees the menu item do
        # nothing at all. Surface it like every other history failure.
        show_error(
            app, "Statistics",
            "Could not read the transcription history.",
            detail=str(e),
        )
        return

    top = tk.Toplevel(app)
    top.title("Statistics")
    top.transient(app)
    top.resizable(False, False)
    body = ttk.Frame(top, padding=16)
    body.pack(fill="both", expand=True)

    rows = [
        (
            "Downloads",
            f"{s['downloads_finished']} / {s['downloads_total']} finished",
        ),
        (
            "Transcriptions",
            f"{s['transcriptions_finished']} / {s['transcriptions_total']} finished",
        ),
        (
            "Total transcription time",
            f"{s['transcription_minutes']} minute(s)",
        ),
        (
            "Top languages",
            ", ".join(f"{lang} ({c})" for lang, c in s["top_languages"]) or "none",
        ),
    ]
    for i, (label, value) in enumerate(rows):
        ttk.Label(
            body, text=label, font=("TkDefaultFont", 9, "bold"),
        ).grid(row=i, column=0, sticky="ne", padx=(0, 14), pady=4)
        ttk.Label(
            body, text=value, wraplength=280, justify="left",
        ).grid(row=i, column=1, sticky="w", pady=4)

    ttk.Button(body, text="Close", command=top.destroy).grid(
        row=len(rows), column=0, columnspan=2, sticky="e", pady=(14, 0)
    )

    top.update_idletasks()
    try:
        x = app.winfo_rootx() + (app.winfo_width() - top.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - top.winfo_height()) // 2
        top.geometry(f"+{max(x, 0)}+{max(y, 0)}")
    except tk.TclError:
        pass
    try:
        top.grab_set()
    except tk.TclError:
        pass
