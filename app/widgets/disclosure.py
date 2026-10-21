"""A disclosure: one clickable header line ("▸ More options") that shows or hides a body.

Generic, so a tab can hide its rarely used options behind it (the Transcribe tab first; the
Download tab is next). The open/closed state lives in a config key the caller names, so it
survives a restart; the caller saves the config when ``on_toggle`` runs.

Keyboard: the header takes focus with Tab and toggles on Return, space or a click; while it
has the focus its text is underlined, since a ``ttk.Label`` draws no focus ring of its own.
Unlike ``app.widgets.tooltip.collapsible_section`` (a mouse-only muted header for a Settings
section), this one is a widget with state, made for the main tabs.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Callable

from app.theme import tokens

CLOSED_MARK = "▸ "
OPEN_MARK = "▾ "


class Disclosure(ttk.Frame):
    """``Disclosure(parent, title, config=cfg, key="x_open")``; build the content with
    ``.body`` as its parent. ``config[key]`` (missing = closed) is read once at build and
    written on every toggle, then ``on_toggle`` runs. ``config`` may be a function that
    returns the dict, for an owner that replaces its config dict (App.app_config after a
    reload): the toggle then writes into the current one."""

    def __init__(
        self,
        parent: tk.Misc,
        title: str,
        *,
        config: "dict[str, Any] | Callable[[], dict[str, Any]]",
        key: str,
        on_toggle: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self._title = title
        self._config = config
        self._key = key
        self._on_toggle = on_toggle
        self._open = bool(self._current_config().get(key, False))
        self.header = ttk.Label(
            self, foreground=tokens.themed(tokens.LINK), cursor="hand2", takefocus=True,
        )
        self.header.pack(anchor="w")
        self.body = ttk.Frame(self)
        try:
            base = tkfont.nametofont("TkDefaultFont")
            self._plain_font = tkfont.Font(font=base)
            self._focus_font = tkfont.Font(font=base)
            self._focus_font.configure(underline=True)
            self.header.configure(font=self._plain_font)
        except tk.TclError:
            self._plain_font = self._focus_font = None
        self.header.bind("<Button-1>", self._on_activate)
        for key_name in ("<Return>", "<KP_Enter>", "<space>"):
            self.header.bind(key_name, self._on_activate)
        self.header.bind("<FocusIn>", lambda _e: self._show_focus(True))
        self.header.bind("<FocusOut>", lambda _e: self._show_focus(False))
        self._render()

    def _current_config(self) -> dict[str, Any]:
        return self._config() if callable(self._config) else self._config

    @property
    def is_open(self) -> bool:
        return self._open

    def set_open(self, open_: bool, *, remember: bool = True) -> None:
        """Show or hide the body, record the state in the config and run ``on_toggle``
        (only when the state changed). ``remember=False`` shows or hides it for this
        session only: the config is left alone and ``on_toggle`` does not run (the
        Download tab opens itself when a time range is set, which is not a preference)."""
        open_ = bool(open_)
        if open_ == self._open:
            return
        self._open = open_
        self._render()
        if not remember:
            return
        self._current_config()[self._key] = open_
        if self._on_toggle is not None:
            self._on_toggle()

    def toggle(self) -> None:
        self.set_open(not self._open)

    def _on_activate(self, _event: object = None) -> str:
        self.toggle()
        return "break"

    def _render(self) -> None:
        self.header.configure(text=(OPEN_MARK if self._open else CLOSED_MARK) + self._title)
        if self._open:
            self.body.pack(fill="x", pady=(6, 0))
        else:
            self.body.pack_forget()

    def _show_focus(self, focused: bool) -> None:
        if self._plain_font is None or self._focus_font is None:
            return
        self.header.configure(font=self._focus_font if focused else self._plain_font)
