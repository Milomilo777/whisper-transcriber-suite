"""Shared hover-tooltip helper + a small "(?)" help-icon widget.

Every tab and dialog in the app builds its own ttk widgets; before this
module existed each place that wanted a hover explanation (only the R3
device badge did) re-implemented the same borderless-Toplevel popup from
scratch. This module is the single implementation everyone else should
use, so every section can get a small hover explanation without repeating
the popup plumbing.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Callable, Union

TextOrGetter = Union[str, Callable[[], str]]

_BG = "#ffffe0"
_FG = "#000000"
_WRAP = 340
# Standard tooltip grace period (Windows uses ~400-500 ms): sweeping the
# mouse across the UI shouldn't flash a popup at every widget it crosses.
_DELAY_MS = 450
# "question_arrow" is one of Tk's cross-platform standard cursor names
# (X11 cursor font, mapped by Tk on Windows/macOS too); guarded anyway
# since not every Tk build ships every named cursor.
_CURSOR = "question_arrow"


def bind_tooltip(
    widget: tk.Widget, text: TextOrGetter, *,
    wraplength: int = _WRAP, delay_ms: int = _DELAY_MS,
) -> None:
    """Show a classic yellow tooltip near *widget* on hover.

    *text* may be a plain string or a zero-arg callable returning the
    current text, for tooltips whose content changes at runtime (e.g. a
    status badge). The popup is a borderless Toplevel, shown after a
    short grace delay, destroyed on <Leave> or on any click so it never
    lingers.
    """
    state: dict[str, Any] = {"tip": None, "after": None}

    def _resolve() -> str:
        try:
            return text() if callable(text) else text
        except Exception:  # noqa: BLE001
            return ""

    def _position(tip: tk.Toplevel) -> tuple[int, int]:
        x = widget.winfo_rootx() + 12
        y = widget.winfo_rooty() + widget.winfo_height() + 4
        # Keep the popup on-screen near the right/bottom edges — but only
        # when the widget itself is on the primary monitor:
        # winfo_screenwidth/height describe the primary display only, so
        # "clamping" a tooltip for a window sitting on a secondary monitor
        # would fling it onto the wrong screen.
        screen_w = widget.winfo_screenwidth()
        screen_h = widget.winfo_screenheight()
        if 0 <= widget.winfo_rootx() < screen_w and 0 <= widget.winfo_rooty() < screen_h:
            if x + tip.winfo_reqwidth() > screen_w:
                x = max(screen_w - tip.winfo_reqwidth() - 4, 0)
            if y + tip.winfo_reqheight() > screen_h:
                # Flip above the widget rather than run off the bottom.
                y = max(widget.winfo_rooty() - tip.winfo_reqheight() - 4, 0)
        return x, y

    def _show() -> None:
        state["after"] = None
        if state["tip"] is not None:
            return
        msg = _resolve()
        if not msg:
            return
        try:
            tip = tk.Toplevel(widget)
            # Withdraw until sized + positioned, so it can't flash at the
            # window manager's default spot before wm_geometry lands.
            tip.wm_withdraw()
            tip.wm_overrideredirect(True)
            try:
                tip.wm_attributes("-topmost", True)
            except tk.TclError:
                pass
            tk.Label(
                tip, text=msg, justify="left",
                background=_BG, foreground=_FG,
                relief="solid", borderwidth=1, wraplength=wraplength,
                padx=6, pady=4,
            ).pack()
            tip.update_idletasks()
            x, y = _position(tip)
            # Explicit sign (no literal "+"): Tk's geometry parser reads
            # "+-500" (a literal "+" followed by a negative number) as
            # "500px from the right edge", not "-500 from the left" --
            # a real trap on a secondary monitor placed left of the
            # primary, where winfo_rootx() is negative.
            tip.wm_geometry(f"{x:+d}{y:+d}")
            tip.wm_deiconify()
            state["tip"] = tip
        except Exception:  # noqa: BLE001
            state["tip"] = None

    def _schedule(_event: Any) -> None:
        if state["tip"] is not None or state["after"] is not None:
            return
        try:
            state["after"] = widget.after(delay_ms, _show)
        except tk.TclError:
            state["after"] = None

    def _hide(_event: Any) -> None:
        after_id = state["after"]
        state["after"] = None
        if after_id is not None:
            try:
                widget.after_cancel(after_id)
            except tk.TclError:
                pass
        tip = state["tip"]
        state["tip"] = None
        if tip is not None:
            try:
                tip.destroy()
            except Exception:  # noqa: BLE001
                pass

    widget.bind("<Enter>", _schedule, add="+")
    widget.bind("<Leave>", _hide, add="+")
    widget.bind("<ButtonPress>", _hide, add="+")
    widget.bind("<Destroy>", _hide, add="+")


def help_icon(parent: tk.Misc, text: TextOrGetter, *, wraplength: int = _WRAP) -> ttk.Label:
    """A small "ⓘ" label that shows *text* as a hover tooltip.

    Pack/grid the returned Label next to a control or a section's title.
    """
    icon = ttk.Label(parent, text=" ⓘ ", foreground="#3a7bd5")
    # Bumped size + bold (2026-08-15): at the default label font size the
    # icon was the same weight as surrounding body text and easy to miss
    # entirely in a dense settings dialog -- confirmed by a real-mouse
    # hover test where the popup worked perfectly once found, but the
    # glyph itself blended in. A fresh, unnamed Font clone (not a Tk
    # *named* font) avoids leaking a global font that a second, unrelated
    # Tk interpreter (e.g. a later test's own tk.Tk()) wouldn't have.
    try:
        base = tkfont.nametofont("TkDefaultFont")
        base_size = base.cget("size")
        icon_font = tkfont.Font(
            family=base.cget("family"),
            size=base_size + (3 if base_size >= 0 else -3),
            weight="bold",
        )
        icon.configure(font=icon_font)
        # Keep the Font object alive for as long as the widget is; Tk
        # drops an unnamed font's backing resource once nothing
        # references the Python object anymore.
        icon._help_icon_font_ref = icon_font  # type: ignore[attr-defined]
    except tk.TclError:
        pass
    try:
        icon.configure(cursor=_CURSOR)
    except tk.TclError:
        pass
    bind_tooltip(icon, text, wraplength=wraplength)
    return icon


def section_labelframe(
    parent: tk.Misc, title: str, help_text: str, *, wraplength: int = _WRAP, **kwargs: object,
) -> ttk.LabelFrame:
    """Build a ``ttk.LabelFrame`` whose title bar itself carries the hover
    help, via ``labelwidget=`` instead of the plain ``text=`` option.

    Tk renders a labelwidget in its own reserved spot, structurally
    separate from whatever grid/pack content the frame holds — so unlike
    a place()-based corner badge, there is no coordinate guessing and no
    way for it to ever overlap real content, regardless of what that
    section's first row looks like.
    """
    frame = ttk.LabelFrame(parent, **kwargs)  # type: ignore[arg-type]
    header = ttk.Frame(frame)
    ttk.Label(header, text=title).pack(side="left")
    help_icon(header, help_text, wraplength=wraplength).pack(side="left", padx=(4, 0))
    frame.configure(labelwidget=header)
    return frame


def collapsible_section(
    parent: tk.Misc, title: str, *, expanded: bool = False, muted: bool = True,
) -> tuple[ttk.Frame, ttk.Frame]:
    """A one-line clickable header ("▸ title") that shows/hides a body.

    Returns ``(outer, holder)``: lay ``outer`` out like any section and build
    the content with ``holder`` as its parent; ``holder`` is packed only while
    expanded. ``muted`` draws the header in light grey so a rarely used,
    optional section stays out of the way (owner request for the Google
    Cloud / Gemini setup in Settings).
    """
    outer = ttk.Frame(parent)
    header = ttk.Label(
        outer,
        foreground="#a0a0a0" if muted else "#1a73e8",
        cursor="hand2",
        font=("TkDefaultFont", 9),
    )
    header.pack(anchor="w")
    holder = ttk.Frame(outer)
    state = {"open": expanded}

    def _render() -> None:
        header.configure(text=("▾ " if state["open"] else "▸ ") + title)
        if state["open"]:
            holder.pack(fill="x", pady=(4, 0))
        else:
            holder.pack_forget()

    def _toggle(_event: object = None) -> None:
        state["open"] = not state["open"]
        _render()

    header.bind("<Button-1>", _toggle)
    _render()
    outer.toggle = _toggle  # type: ignore[attr-defined]
    outer.is_open = lambda: state["open"]  # type: ignore[attr-defined]
    outer.muted = muted  # type: ignore[attr-defined]
    outer.header = header  # type: ignore[attr-defined]
    return outer, holder
