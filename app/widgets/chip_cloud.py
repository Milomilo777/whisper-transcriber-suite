"""A wrapping row of rounded "chips" (pill buttons) drawn on one Canvas.

Used by the Supreme Master TV tab for its program shortcuts. The chips flow
left to right and wrap to the width of the widget. Collapsed, only the first
row shows, ending in a "+N more" chip; expanded, every chip shows and the
last one reads "Show less". The chip whose label equals ``selected`` is drawn
filled in the brand colour.

Keyboard: the canvas takes the focus with Tab; Left/Right (and Home/End)
move between chips, Return or Space activates the focused chip. A 2 px ring
marks the focused chip. Colours come from this module's two palettes and are
redrawn on <<ThemeChanged>>, because Canvas items are not reached by the
theme colour swap.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Callable

from app.dpi import scale_factor
from app.theme import tokens

# Sizes at 96 dpi; scaled by the window's DPI factor when drawn.
CHIP_H = 30
PAD_X = 14
GAP = 8
RING = 2
MARGIN = RING + 2  # room around the chips for the focus ring

PALETTES = {
    "light": {
        "normal_bg": "#eef2f4", "normal_fg": "#1f2937",
        "hover_bg": "#dfe8eb", "hover_fg": "#0f172a",
        "selected_bg": "#207a80", "selected_fg": "#ffffff",
        "toggle_fg": "#1b666b", "ring": "#207a80",
    },
    "dark": {
        "normal_bg": "#2d3238", "normal_fg": "#e5e7eb",
        "hover_bg": "#3a4149", "hover_fg": "#ffffff",
        "selected_bg": "#207a80", "selected_fg": "#ffffff",
        "toggle_fg": "#6fd3da", "ring": "#4fd1db",
    },
}


@dataclass
class _Chip:
    label: str
    text: str
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    toggle: bool = False


def flow_layout(widths: list[float], avail: float, gap: float, row_h: float,
                margin: float = 0.0) -> list[tuple[float, float]]:
    """Top-left corner of each item when they wrap within ``avail`` pixels.

    An item wider than the whole row still gets a row of its own.
    """
    out: list[tuple[float, float]] = []
    x, y = margin, margin
    for w in widths:
        if x > margin and x + w > avail - margin:
            x, y = margin, y + row_h + gap
        out.append((x, y))
        x += w + gap
    return out


class ChipCloud(tk.Canvas):
    """Program shortcuts as rounded chips; ``command(label)`` runs on activation."""

    def __init__(self, master: tk.Misc, labels: list[str], command: Callable[[str], None],
                 *, display: Callable[[str], str] = lambda s: s, background: str = "") -> None:
        super().__init__(master, highlightthickness=0, borderwidth=0, takefocus=1, height=1)
        if background:
            self.configure(background=background)
        self.labels = list(labels)
        self.command = command
        self.display = display
        self.selected: str | None = None
        self.expanded = False
        self.focus_index = 0
        self.hover_index: int | None = None
        self._chips: list[_Chip] = []
        self._has_focus = False
        self._font = tkfont.nametofont("TkDefaultFont").copy()
        self._bold = self._font.copy()
        self._bold.configure(weight="bold")
        self.bind("<Configure>", lambda _e: self.redraw(), add="+")
        self.bind("<<ThemeChanged>>", lambda _e: self.after_idle(self.redraw), add="+")
        self.bind("<Motion>", self._on_motion, add="+")
        self.bind("<Leave>", self._on_leave, add="+")
        self.bind("<Button-1>", self._on_click, add="+")
        self.bind("<FocusIn>", lambda _e: self._set_focus(True), add="+")
        self.bind("<FocusOut>", lambda _e: self._set_focus(False), add="+")
        for key, step in (("<Left>", -1), ("<Right>", 1), ("<Up>", -1), ("<Down>", 1)):
            self.bind(key, lambda _e, s=step: self._move(s), add="+")
        self.bind("<Home>", lambda _e: self._move_to(0), add="+")
        self.bind("<End>", lambda _e: self._move_to(len(self._chips) - 1), add="+")
        self.bind("<Return>", self._on_key_activate, add="+")
        self.bind("<space>", self._on_key_activate, add="+")

    # ---------------------------------------------------------------- state
    def set_selected(self, label: str | None) -> None:
        if label != self.selected:
            self.selected = label
            self.redraw()

    def palette(self) -> dict[str, str]:
        return PALETTES["light" if tokens.current_theme() == "light" else "dark"]

    # --------------------------------------------------------------- layout
    def _metrics(self) -> tuple[float, float, float, float]:
        k = scale_factor(self)
        return CHIP_H * k, PAD_X * k, GAP * k, MARGIN * k

    def _chip_width(self, text: str, bold: bool, pad: float) -> float:
        return (self._bold if bold else self._font).measure(text) + 2 * pad

    def _layout(self) -> list[_Chip]:
        h, pad, gap, margin = self._metrics()
        avail = max(self.winfo_width(), 200)
        chips = [_Chip(lb, self.display(lb)) for lb in self.labels]
        for c in chips:
            c.w = self._chip_width(c.text, c.label == self.selected, pad)
        if self.expanded:
            chips.append(_Chip("", "Show less", toggle=True))
            chips[-1].w = self._chip_width(chips[-1].text, True, pad)
            shown = chips
        else:
            # Keep as many chips as fit on the first row next to the "+N more" chip.
            shown = []
            for i, c in enumerate(chips):
                rest = len(chips) - i - 1
                more_w = self._chip_width(f"+{rest} more", True, pad) + gap if rest else 0
                used = sum(s.w + gap for s in shown)
                if margin + used + c.w + more_w > avail - margin and shown:
                    break
                shown.append(c)
            hidden = len(chips) - len(shown)
            if hidden:
                more = _Chip("", f"+{hidden} more", toggle=True)
                more.w = self._chip_width(more.text, True, pad)
                shown.append(more)
        for c, (x, y) in zip(shown, flow_layout([c.w for c in shown], avail, gap, h, margin)):
            c.x, c.y = x, y
        return shown

    # ----------------------------------------------------------------- draw
    def redraw(self) -> None:
        try:
            self.delete("all")
        except tk.TclError:
            return
        self._chips = self._layout()
        self.focus_index = min(self.focus_index, max(0, len(self._chips) - 1))
        h, _pad, _gap, margin = self._metrics()
        pal = self.palette()
        for i, c in enumerate(self._chips):
            if c.label and c.label == self.selected:
                bg, fg = pal["selected_bg"], pal["selected_fg"]
            elif i == self.hover_index:
                bg, fg = pal["hover_bg"], pal["hover_fg"]
            else:
                bg, fg = pal["normal_bg"], (pal["toggle_fg"] if c.toggle else pal["normal_fg"])
            self._pill(c.x, c.y, c.w, h, fill=bg, tags=(f"chip{i}",))
            bold = c.toggle or (c.label == self.selected)
            self.create_text(c.x + c.w / 2, c.y + h / 2, text=c.text, fill=fg,
                             font=self._bold if bold else self._font, tags=(f"chip{i}",))
            if self._has_focus and i == self.focus_index:
                r = RING * scale_factor(self)
                self._pill(c.x - r - 1, c.y - r - 1, c.w + 2 * r + 2, h + 2 * r + 2,
                           outline=pal["ring"], width=r, fill="")
        bottom = max((c.y for c in self._chips), default=0) + h + margin
        if int(float(self.cget("height"))) != int(bottom):
            self.configure(height=int(bottom))

    def _pill(self, x: float, y: float, w: float, h: float, *, fill: str,
              outline: str = "", width: float = 0, tags: tuple[str, ...] = ()) -> None:
        """A rounded rectangle with semicircle ends (ovals + a rectangle, or arcs + lines for a ring)."""
        r = h / 2
        if fill:
            self.create_oval(x, y, x + h, y + h, fill=fill, outline="", tags=tags)
            self.create_oval(x + w - h, y, x + w, y + h, fill=fill, outline="", tags=tags)
            self.create_rectangle(x + r, y, x + w - r, y + h, fill=fill, outline="", tags=tags)
        if outline:
            self.create_arc(x, y, x + h, y + h, start=90, extent=180, style="arc",
                            outline=outline, width=width)
            self.create_arc(x + w - h, y, x + w, y + h, start=-90, extent=180, style="arc",
                            outline=outline, width=width)
            self.create_line(x + r, y, x + w - r, y, fill=outline, width=width)
            self.create_line(x + r, y + h, x + w - r, y + h, fill=outline, width=width)

    # --------------------------------------------------------------- events
    def _index_at(self, x: float, y: float) -> int | None:
        h, *_ = self._metrics()
        for i, c in enumerate(self._chips):
            if c.x <= x <= c.x + c.w and c.y <= y <= c.y + h:
                return i
        return None

    def _on_motion(self, e: "tk.Event[tk.Misc]") -> None:
        i = self._index_at(self.canvasx(e.x), self.canvasy(e.y))
        self.configure(cursor="hand2" if i is not None else "")
        if i != self.hover_index:
            self.hover_index = i
            self.redraw()

    def _on_leave(self, _e: object) -> None:
        if self.hover_index is not None:
            self.hover_index = None
            self.redraw()

    def _on_click(self, e: "tk.Event[tk.Misc]") -> None:
        i = self._index_at(self.canvasx(e.x), self.canvasy(e.y))
        if i is not None:
            self.focus_index = i
            self.activate(i)

    def _on_key_activate(self, _e: object) -> str:
        self.activate(self.focus_index)
        return "break"

    def _set_focus(self, on: bool) -> None:
        self._has_focus = on
        self.redraw()

    def _move(self, step: int) -> str:
        if self._chips:
            self.focus_index = (self.focus_index + step) % len(self._chips)
            self.redraw()
        return "break"

    def _move_to(self, index: int) -> str:
        if self._chips:
            self.focus_index = max(0, min(index, len(self._chips) - 1))
            self.redraw()
        return "break"

    def activate(self, index: int) -> None:
        """Run the chip at ``index``: a program shortcut, or the more/less toggle."""
        if not (0 <= index < len(self._chips)):
            return
        chip = self._chips[index]
        if chip.toggle:
            self.expanded = not self.expanded
            self.redraw()
            return
        self.set_selected(chip.label)
        self.command(chip.label)
