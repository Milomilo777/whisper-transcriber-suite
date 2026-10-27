"""The macOS microphone notice: what the permission is for and where to turn it on.

Without it, a user who answered "Don't Allow" to macOS's one-time question gets a Live tab that
listens to silence and says nothing. Two wordings, chosen by ``app.mac_permissions.notice_reason``:
before macOS asks (explain, nothing to click but Close) and when the microphone is blocked or
silent (a button opens the right System Settings page). Never built on Windows or Linux: the
callers check the platform first.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from app import mac_permissions
from app.dpi import px
from app.i18n import _


def build_mic_notice(
    master: "tk.Misc", reason: str, *, opener: Optional[Callable[[], bool]] = None,
) -> tk.Toplevel:
    """Build the (not yet modal) notice; ``dialog.opened_settings`` tells what the user chose."""
    open_settings = opener or mac_permissions.open_microphone_settings
    dialog = tk.Toplevel(master)
    dialog.title(_("Microphone access"))
    dialog.transient(master)  # type: ignore[arg-type]
    dialog.resizable(False, False)
    setattr(dialog, "opened_settings", False)

    body = ttk.Frame(dialog, padding=16)
    body.pack(fill="both", expand=True)
    if reason == mac_permissions.REASON_BLOCKED:
        text = _("macOS is not giving this app the microphone, or the microphone is muted. "
                 "Allow it in System Settings, Privacy & Security, Microphone.")
    else:
        text = _("macOS will ask whether this app may use the microphone. "
                 "Choose Allow, so that live listening can hear you.")
    ttk.Label(body, text=text, wraplength=px(420), justify="left").pack(anchor="w")

    actions = ttk.Frame(body)
    actions.pack(fill="x", pady=(14, 0))
    close = ttk.Button(actions, text=_("Close"), command=dialog.destroy)
    close.pack(side="right")
    if reason == mac_permissions.REASON_BLOCKED:
        def go() -> None:
            setattr(dialog, "opened_settings", True)
            open_settings()
            dialog.destroy()

        ttk.Button(actions, text=_("Open System Settings"), style="Accent.TButton",
                   command=go).pack(side="right", padx=(0, 8))
    dialog.bind("<Escape>", lambda _e: dialog.destroy())
    return dialog


def show_mic_notice(
    master: "tk.Misc", reason: str, *, opener: Optional[Callable[[], bool]] = None,
) -> bool:
    """Show the notice and wait; True when the user opened System Settings."""
    dialog = build_mic_notice(master, reason, opener=opener)
    dialog.update_idletasks()
    try:
        top = master.winfo_toplevel()
        x = top.winfo_rootx() + (top.winfo_width() - dialog.winfo_reqwidth()) // 2
        y = top.winfo_rooty() + (top.winfo_height() - dialog.winfo_reqheight()) // 3
        dialog.geometry(f"+{x}+{y}")
    except tk.TclError:
        pass
    try:
        dialog.grab_set()
    except tk.TclError:
        pass  # headless runs cannot always grab
    master.wait_window(dialog)
    return bool(getattr(dialog, "opened_settings", False))
