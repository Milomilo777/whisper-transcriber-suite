"""Modal-grab hand-over between a dialog and its child window.

Tk keeps a single grab per display and does not stack them: a child's
``grab_set()`` silently replaces the owner's, and destroying the child
does NOT hand the grab back — the owner stays non-modal for the rest of
its life, so the user can interact with the main window while the
dialog's unsaved fields are still live. The Report-a-problem window, the
error dialog and the HardwareWizard each carry a local copy of this
dance; this module is the shared version for new call sites.
"""
from __future__ import annotations

import tkinter as tk

#: Poll a few times for a viewable child before grabbing; never block on
#: wait_visibility(), which would freeze the app when no window can map
#: (minimised main window, no visible desktop).
_GRAB_TRIES = 50
_GRAB_POLL_MS = 20


def take_grab_over(owner: tk.Misc, dlg: tk.Toplevel) -> None:
    """Move the modal grab from *owner* to *dlg* and give it back on close.

    On macOS a child of a grabbing window gets no mouse clicks, so the grab
    must move to the child while it is open. If *owner* did not hold the
    grab (a popup opened from a non-modal context) nothing is restored —
    the grab simply ends with the child, exactly like a plain ``grab_set``.
    """
    try:
        had_grab = owner.grab_current() is owner
    except tk.TclError:
        had_grab = False
    if had_grab:
        owner.grab_release()

    def _grab_when_viewable(tries: int = 0) -> None:
        try:
            if not dlg.winfo_exists():
                return
            if dlg.winfo_viewable():
                dlg.grab_set()
            elif tries < _GRAB_TRIES:
                dlg.after(_GRAB_POLL_MS, lambda: _grab_when_viewable(tries + 1))
        except tk.TclError:
            pass  # the window still works without a grab

    _grab_when_viewable()

    def _give_back(event: "tk.Event[tk.Misc]") -> None:
        if event.widget is not dlg or not had_grab:
            return
        try:
            if not owner.winfo_exists():
                return
            current = owner.grab_current()
            # During <Destroy> the dying window's grab may still be
            # reported as current, so accept both "no grab" and "the grab
            # is the dying dialog"; anything newer must not be stolen.
            if current is None or current is dlg:
                owner.grab_set()
        except tk.TclError:
            pass

    dlg.bind("<Destroy>", _give_back, add="+")
