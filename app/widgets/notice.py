"""Quiet notices: short, non-blocking messages that replace pure-information message boxes.

A notice appears along the bottom edge of a window, hides itself after a few seconds, stays
while the mouse is over it and never takes the keyboard focus. Use it only for text that needs
no decision ("saved", "copied", "nothing found"); questions, errors that need action, consent and
data-loss warnings stay dialogs.

``notify(widget, text)`` is the one entry point. Each top-level window gets its own
``NoticeHost`` the first time it is asked, so a transcript viewer shows its notices in its own
window. The notice is laid out with ``place`` over the bottom edge, so it works with any layout
manager the window already uses. At most ``MAX_QUEUE`` notices are held (the one on screen plus
those waiting); a newer notice pushes out the oldest waiting one.

Keyboard: ``Ctrl+.`` dismisses the notice on screen from anywhere in the window; Tab reaches the
close button (Enter/Space/Escape close it there). Escape alone is not bound on the window,
because windows already use it for "cancel" and "close".
"""
from __future__ import annotations

import logging
import tkinter as tk
from collections import deque
from tkinter import ttk
from typing import Deque, Literal

from app.theme import tokens

logger = logging.getLogger(__name__)

MAX_QUEUE = 3
BASE_MS = 4000
PER_CHAR_MS = 40
MAX_MS = 9000
LEAVE_GRACE_MS = 1500  # how long a notice lingers after the pointer leaves it
DISMISS_SEQUENCE = "<Control-period>"

Kind = Literal["info", "success", "warning"]
_ACCENT = {
    "info": tokens.LINK,
    "success": tokens.SUCCESS_TEXT,
    "warning": tokens.WARNING_TEXT,
}
_HOST_ATTR = "_wts_notice_host"
_WRAP_MIN = 220


def duration_ms(text: str) -> int:
    """How long a notice stays: a few seconds, a little longer for longer text."""
    return min(MAX_MS, BASE_MS + PER_CHAR_MS * len(text))


class NoticeHost:
    """The notice area of one top-level window."""

    def __init__(self, window: tk.Misc) -> None:
        self.window = window
        self.pending: Deque[tuple[str, Kind]] = deque()
        self.current: tuple[str, Kind] | None = None
        self._after_id: str | None = None
        self._hovered = False
        self._expired_while_hovered = False

        self.frame = ttk.Frame(window, padding=(0, 0, 8, 0))
        self._accent = tk.Frame(self.frame, width=4, bg=_ACCENT["info"])
        self._accent.pack(side="left", fill="y")
        ttk.Separator(self.frame, orient="horizontal").place(x=0, y=0, relwidth=1)
        self._text = tk.StringVar(master=self.frame, value="")
        self.label = ttk.Label(self.frame, textvariable=self._text, anchor="w", justify="left")
        self.label.pack(side="left", fill="x", expand=True, padx=(tokens.SPACE_SM, tokens.SPACE_SM),
                        pady=tokens.SPACE_SM)
        self.close_button = ttk.Button(self.frame, text="×", width=3, command=self.dismiss,
                                       takefocus=True)
        self.close_button.pack(side="right", pady=tokens.SPACE_XS)
        self.frame.bind("<Configure>", self._rewrap, add="+")
        for widget in (self.frame, self.label, self._accent, self.close_button):
            widget.bind("<Enter>", self._on_enter, add="+")
            widget.bind("<Leave>", self._on_leave, add="+")
        self.close_button.bind("<Escape>", self._on_escape, add="+")
        window.bind(DISMISS_SEQUENCE, self._on_dismiss_key, add="+")

    # ------------------------------------------------------------------ state
    @property
    def visible(self) -> bool:
        return self.current is not None

    @property
    def queued(self) -> int:
        """Notices held: the one on screen plus those waiting."""
        return len(self.pending) + (1 if self.current is not None else 0)

    def post(self, text: str, kind: Kind = "info") -> None:
        text = " ".join(text.split())
        if not text:
            return
        if kind not in _ACCENT:
            kind = "info"
        if self.current is None:
            self._show((text, kind))
            return
        if self.current == (text, kind):
            # the same message again: one notice, but it stays a little longer and on top
            self.frame.lift()
            if not self._hovered:
                self._arm_timer(duration_ms(text))
            return
        if (text, kind) in self.pending:
            return
        while self.queued >= MAX_QUEUE:
            self.pending.popleft()
        self.pending.append((text, kind))

    def dismiss(self) -> None:
        """Close the notice on screen and show the next waiting one, if any."""
        self._cancel_timer()
        self.current = None
        self._hovered = False
        self._expired_while_hovered = False
        if self.pending:
            self._show(self.pending.popleft())
        else:
            self.frame.place_forget()

    # ---------------------------------------------------------------- display
    def _show(self, item: tuple[str, Kind]) -> None:
        text, kind = item
        self.current = item
        self._text.set(text)
        self._accent.configure(bg=_ACCENT[kind])
        self._expired_while_hovered = False
        self.frame.place(relx=0.0, rely=1.0, anchor="sw", relwidth=1.0)
        self.frame.lift()  # above its siblings; lifting never moves the keyboard focus
        self._arm_timer(duration_ms(text))

    def _rewrap(self, event: "tk.Event[tk.Misc]") -> None:
        room = int(event.width) - self.close_button.winfo_reqwidth() - 40
        self.label.configure(wraplength=max(_WRAP_MIN, room))

    # ------------------------------------------------------------------ timer
    def _arm_timer(self, ms: int) -> None:
        self._cancel_timer()
        self._after_id = self.window.after(ms, self._on_timeout)

    def _cancel_timer(self) -> None:
        if self._after_id is not None:
            try:
                self.window.after_cancel(self._after_id)
            except tk.TclError:
                logger.debug("notice timer already gone", exc_info=True)
            self._after_id = None

    def _on_timeout(self) -> None:
        self._after_id = None
        if self._hovered:
            self._expired_while_hovered = True  # hide as soon as the pointer leaves
            return
        self.dismiss()

    # --------------------------------------------------------- pointer + keys
    def _on_enter(self, *_args: object) -> None:
        self._hovered = True
        self._cancel_timer()

    def _on_leave(self, *_args: object) -> None:
        # <Leave> also fires when the pointer moves between the notice's own children.
        # Ask Tk where the pointer is; a pointer still inside the frame is still hovering.
        try:
            x, y = self.frame.winfo_pointerxy()
            inside = self.frame.winfo_containing(x, y)
        except tk.TclError:
            inside = None
        frame_path = str(self.frame)
        if inside is not None and (str(inside) == frame_path or str(inside).startswith(frame_path + ".")):
            return
        self._hovered = False
        if self.current is None:
            return
        if self._expired_while_hovered:
            self.dismiss()
        elif self._after_id is None:
            self._arm_timer(LEAVE_GRACE_MS)

    def _on_escape(self, *_args: object) -> str:
        self.dismiss()
        return "break"

    def _on_dismiss_key(self, *_args: object) -> str | None:
        if self.current is None:
            return None  # nothing to dismiss: let the window handle the key as before
        self.dismiss()
        return "break"


def host_for(widget: tk.Misc) -> NoticeHost:
    """The ``NoticeHost`` of the top-level window that holds ``widget`` (made on first use)."""
    window = widget.winfo_toplevel()
    host = getattr(window, _HOST_ATTR, None)
    if host is None:
        host = NoticeHost(window)
        setattr(window, _HOST_ATTR, host)
    return host


def notify(widget: tk.Misc, text: str, kind: Kind = "info") -> None:
    """Show ``text`` as a quiet notice in the window that holds ``widget``.

    Never raises for a window that is already being destroyed (the notice is simply lost, and
    the line goes to the log so the message is not silently dropped).
    """
    try:
        host_for(widget).post(text, kind)
    except tk.TclError:
        logger.info("notice not shown (window closing): %s", text)
