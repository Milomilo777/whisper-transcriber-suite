"""ModelLoadingDialog — modal Toplevel shown while the Whisper model
loads on first transcribe.

Companion to :mod:`app.dialogs.model_download` (which drives the
*download* of the model). This dialog is the much simpler sibling:
the bytes are already on disk; we only need to wait for a worker
subprocess to import faster-whisper and load the weights into RAM.

Lifecycle:

* Caller constructs the dialog and immediately calls
  ``self.wait_window(dialog)``.
* While the dialog is up, the App's :func:`poll` loop will see a
  ``ready`` event for the freshly-spawned worker and, via the
  ``_main_thread_calls`` queue, mark this dialog's
  :attr:`success` ``True`` then call :meth:`destroy`.
* If the user clicks Cancel first, :attr:`success` stays ``False``
  and the caller is responsible for tearing down the worker.

The dialog itself does NOT spawn the worker or talk to the model
manager — that's the TranscriptionService's job. We just provide a
modal UI surface during the wait.
"""
from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk


def _compute_position(master: "tk.Misc", width: int, height: int) -> tuple[int, int]:
    """Return the top-left ``(x, y)`` for centring a ``width`` x ``height``
    dialog over ``master``.

    Falls back to centring on the primary screen when the master is not
    viewable: Windows reports a minimised window's root coordinates as
    -32000, so the parent-based maths would place the dialog far
    off-screen.

    Negative parent coordinates are kept as-is. A parent living on a
    monitor left of / above the primary has negative root coordinates
    and must not be yanked onto the primary display; the clamp to
    non-negative only applies when the parent itself is on the primary
    display, whose bounds winfo_screenwidth/height describe.
    """
    if not master.winfo_viewable():
        return (
            (master.winfo_screenwidth() - width) // 2,
            (master.winfo_screenheight() - height) // 2,
        )
    x = master.winfo_rootx() + (master.winfo_width() - width) // 2
    y = master.winfo_rooty() + (master.winfo_height() - height) // 2
    if (
        0 <= master.winfo_rootx() < master.winfo_screenwidth()
        and 0 <= master.winfo_rooty() < master.winfo_screenheight()
    ):
        x = max(x, 0)
        y = max(y, 0)
    return x, y


class ModelLoadingDialog(tk.Toplevel):
    """Modal "Loading Whisper model…" dialog with an indeterminate bar.

    Attributes
    ----------
    success : bool
        ``True`` when the model finished loading (caller flips this
        from outside, typically from the worker-event poll loop on
        the Tk main thread). ``False`` if the user clicks Cancel or
        closes the window via the WM_DELETE_WINDOW button.
    """

    def __init__(self, master: "tk.Tk | tk.Toplevel") -> None:
        super().__init__(master)
        self.title("Loading Whisper model")
        self.resizable(False, False)
        self.transient(master)
        self.protocol("WM_DELETE_WINDOW", self.cancel)

        self.success: bool = False
        # Set by whichever close path (cancel / mark_success_and_close)
        # runs first. The App closes this dialog from the worker-event
        # poll loop via a deferred post_to_main callback, which can
        # arrive after the user already clicked Cancel; without this
        # guard that late callback flipped success back to True after
        # the caller had already read False and torn the worker down.
        self._closed: bool = False

        body = ttk.Frame(self, padding=18)
        body.grid(row=0, column=0, sticky="nsew")

        # "Segoe UI" doesn't exist on macOS; fall back to the platform's
        # default UI font there while keeping the Windows look unchanged.
        _title_font = ("TkDefaultFont", 11, "bold") if sys.platform == "darwin" else ("Segoe UI", 11, "bold")
        ttk.Label(
            body,
            text="Loading the Whisper model — this takes a few seconds…",
            font=_title_font,
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            body,
            text=(
                "The model loads once per session. "
                "Subsequent transcriptions start instantly."
            ),
            foreground="#666",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        self.pb = ttk.Progressbar(body, length=420, mode="indeterminate")
        self.pb.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        # .start(N) ticks the indeterminate bar every N ms so the
        # user has visual confirmation the app isn't frozen.
        self.pb.start(10)

        self.cancel_btn = ttk.Button(body, text="Cancel", command=self.cancel)
        self.cancel_btn.grid(row=3, column=0, sticky="e")

        body.columnconfigure(0, weight=1)

        # Centre on parent. update_idletasks first so winfo_width
        # returns the real laid-out width rather than 1.
        self.update_idletasks()
        try:
            x, y = _compute_position(master, self.winfo_width(), self.winfo_height())
            # "+-500" (not "-500") is Tk's accepted form for an absolute
            # negative position; "-500" alone means 500 px from the right
            # screen edge (verified on Windows/Tk 8.6). A parent on a
            # monitor left of the primary legitimately yields negative
            # coordinates, so this form must be preserved.
            self.geometry(f"+{x}+{y}")
        except tk.TclError:
            pass

        # grab_set last — once the layout is settled. Some headless
        # test envs can't grab; that's fine, we just skip.
        try:
            self.grab_set()
        except tk.TclError:
            pass

    def cancel(self) -> None:
        """User pressed Cancel (or closed the window).

        We do NOT kill the worker from here — the caller owns the
        worker lifecycle and reads :attr:`success` after
        ``wait_window`` returns to decide what to do.

        Idempotent, and never runs after :meth:`mark_success_and_close`
        (or vice versa): whichever path closed the dialog first owns
        the final :attr:`success` value.
        """
        if self._closed:
            return
        self._closed = True
        self.success = False
        try:
            self.pb.stop()
        except tk.TclError:
            pass
        try:
            self.cancel_btn.configure(state="disabled")
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass

    def mark_success_and_close(self) -> None:
        """Called from the worker-event poll loop when the spawned
        worker emits its ``ready`` event. Sets :attr:`success`
        ``True`` then closes the dialog so ``wait_window`` returns
        in the caller.

        No-op if the user already closed the dialog (Cancel or the
        window's X button) — a deferred ``post_to_main`` call can land
        after that, and flipping :attr:`success` then would contradict
        the False the caller has already read.
        """
        if self._closed:
            return
        self._closed = True
        self.success = True
        try:
            self.pb.stop()
        except tk.TclError:
            pass
        try:
            self.destroy()
        except tk.TclError:
            pass
