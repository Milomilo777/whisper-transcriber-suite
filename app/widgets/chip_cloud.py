"""A wrapping row of rounded "chips" (pill buttons) drawn on one Canvas.

Used by the Supreme Master TV tab for its program shortcuts and its books. The chips flow
left to right and wrap to the width of the widget. A chip has a tinted fill and a 1 px
border that stands out from the panel on its own (3:1), semibold accent text, and a hand
cursor; the hovered chip darkens, and the chip whose label equals ``selected`` is drawn
solid in the accent colour with a check mark in front of its text.

Collapsed, only the first row shows, ending in a ghost text control ("All programs v");
expanded, every chip shows and the control reads "Show less ^". The control has no fill
or border on purpose, so it never reads as one more category.

Keyboard: the canvas takes the focus with Tab; Left/Right (and Home/End) move between
chips, Return or Space activates the focused chip. A 2 px ring, 2 px away from the chip,
marks the focused one. Colours come from ``tokens.CHIP_PALETTES`` and are redrawn on
<<ThemeChanged>>, because Canvas items are not reached by the theme colour swap.

The module also holds the pill drawing the SMTV banner buttons share: ``render_pill``,
``pill_photo`` and ``flatten``.
"""
from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk
from typing import Callable, Union

from app.dpi import scale_factor
from app.theme import system_fonts, tokens

# Sizes at 96 dpi; scaled by the window's DPI factor when drawn.
CHIP_H = 32
PAD_X = 14
GHOST_PAD = 8
GAP = 8
BORDER = 1
RING = 2
RING_OFFSET = 2
MARGIN = RING + RING_OFFSET  # room around the chips for the focus ring
CHECK = "✓ "
MORE_TEXT = "All programs ▾"
LESS_TEXT = "Show less ▴"
FONT_SIZE = 10

PALETTES = tokens.CHIP_PALETTES

Rgba = tuple[int, int, int, int]
Colour = Union[str, Rgba, None]


# ------------------------------------------------------------------ pill drawing
def hex_rgb(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def flatten(layers: list[tuple[str, float]]) -> Rgba:
    """One RGBA colour that paints like ``layers`` (``(hex, alpha 0..1)``, bottom first).

    The banner pill is a dark scrim plus a white film; flattened to one colour it can be drawn
    as a single image that Tk blends over the gradient behind it.
    """
    alpha = 0.0
    rgb = (0.0, 0.0, 0.0)
    for colour, a in layers:
        new_alpha = a + alpha * (1 - a)
        if new_alpha <= 0:
            continue
        src = hex_rgb(colour)
        rgb = tuple((src[i] * a + rgb[i] * alpha * (1 - a)) / new_alpha for i in range(3))
        alpha = new_alpha
    return round(rgb[0]), round(rgb[1]), round(rgb[2]), round(alpha * 255)


def _rgba(colour: Colour) -> Rgba | None:
    if not colour:
        return None
    if isinstance(colour, str):
        r, g, b = hex_rgb(colour)
        return r, g, b, 255
    return colour


def render_pill(w: int, h: int, fill: Colour, outline: Colour = None, width: int = 0):
    """A rounded rectangle with semicircle ends as a Pillow RGBA image.

    Drawn four times larger and scaled down (Pillow resizes RGBA in premultiplied alpha), so
    the edge is anti-aliased and a translucent fill has no dark fringe. ``fill`` and ``outline`` are hex strings or RGBA
    tuples.
    """
    from PIL import Image, ImageDraw

    iw, ih = max(1, int(w)), max(1, int(h))
    ss = 4
    big = Image.new("RGBA", (iw * ss, ih * ss), (0, 0, 0, 0))
    edge = _rgba(outline)
    ImageDraw.Draw(big).rounded_rectangle(
        (0, 0, iw * ss - 1, ih * ss - 1), radius=ih * ss // 2,
        fill=_rgba(fill), outline=edge, width=max(1, width * ss) if edge else 0)
    return big.resize((iw, ih), Image.Resampling.LANCZOS)


def pill_photo(master: tk.Misc, cache: dict[tuple[object, ...], object], w: float, h: float,
               fill: Colour, outline: Colour = None, width: int = 0):
    """The pill as a PhotoImage, kept in ``cache`` (a PhotoImage must stay referenced)."""
    iw, ih = max(1, round(w)), max(1, round(h))
    key = (iw, ih, fill, outline, width)
    photo = cache.get(key)
    if photo is None:
        from PIL import ImageTk
        photo = ImageTk.PhotoImage(render_pill(iw, ih, fill, outline, width), master=master)
        cache[key] = photo
    return photo


def semibold_font(widget: tk.Misc) -> tkfont.Font:
    """The 10 pt semibold UI font of the chips and the banner pills.

    Windows has a Semibold face; macOS maps the family to its bold system font (see
    ``system_fonts.ui_font``); elsewhere the weight is asked for directly.
    """
    if sys.platform in ("win32", "darwin"):
        spec = system_fonts.ui_font(widget, "Segoe UI Semibold", FONT_SIZE)
    else:
        spec = system_fonts.ui_font(widget, "Segoe UI", FONT_SIZE, "bold")
    family, size, *style = spec
    bold = bool(style) and "bold" in str(style[0]).split()
    return tkfont.Font(root=widget, family=family, size=size, weight="bold" if bold else "normal")


# ---------------------------------------------------------------------- layout
@dataclass
class _Chip:
    label: str
    text: str
    x: float = 0.0
    y: float = 0.0
    w: float = 0.0
    toggle: bool = False
    bg: str = ""


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
                 *, display: Callable[[str], str] = lambda s: s, background: str = "",
                 panel_background: bool = False, more_text: str = MORE_TEXT,
                 less_text: str = LESS_TEXT) -> None:
        super().__init__(master, highlightthickness=0, borderwidth=0, takefocus=1, height=1)
        if background:
            self.configure(background=background)
        self.labels = list(labels)
        self.command = command
        self.display = display
        self.more_text = more_text
        self.less_text = less_text
        self.panel_background = panel_background  # follow the ttk panel colour on a theme switch
        self.selected: str | None = None
        self.expanded = False
        self.focus_index = 0
        self.hover_index: int | None = None
        self._chips: list[_Chip] = []
        self._images: dict[tuple[object, ...], object] = {}  # PhotoImages must stay referenced
        self._has_focus = False
        self._font = semibold_font(self)
        self._underlined = self._font.copy()
        self._underlined.configure(underline=True)
        self.bind("<Configure>", lambda _e: self.redraw(), add="+")
        self.bind("<<ThemeChanged>>", lambda _e: self.after_idle(self._on_theme_changed), add="+")
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

    def _text_of(self, c: _Chip) -> str:
        return CHECK + c.text if c.label and c.label == self.selected else c.text

    def _chip_width(self, text: str, pad: float) -> float:
        return self._font.measure(text) + 2 * pad

    def _toggle(self, text: str) -> _Chip:
        chip = _Chip("", text, toggle=True)
        chip.w = self._chip_width(text, 0)
        return chip

    def _layout(self) -> list[_Chip]:
        h, pad, gap, margin = self._metrics()
        avail = max(self.winfo_width(), 200)
        chips = [_Chip(lb, self.display(lb)) for lb in self.labels]
        for c in chips:
            c.w = self._chip_width(self._text_of(c), pad)
        if self.expanded:
            shown = chips + [self._toggle(self.less_text)]
        else:
            # Keep as many chips as fit on the first row next to the "All programs" control.
            more = self._toggle(self.more_text)
            lead = GHOST_PAD * scale_factor(self)
            shown = []
            for i, c in enumerate(chips):
                more_w = more.w + lead + gap if i < len(chips) - 1 else 0
                used = sum(s.w + gap for s in shown)
                if margin + used + c.w + more_w > avail - margin and shown:
                    break
                shown.append(c)
            if len(shown) < len(chips):
                shown.append(more)
        # The ghost control has no edge of its own: it gets a little air after a chip on its
        # row, and when it starts a row its text lines up with the chips' left edge.
        lead = GHOST_PAD * scale_factor(self)
        widths = [c.w + lead if c.toggle else c.w for c in shown]
        for c, (x, y) in zip(shown, flow_layout(widths, avail, gap, h, margin)):
            c.x, c.y = (x + lead if c.toggle and x > margin else x), y
        return shown

    # ----------------------------------------------------------------- draw
    def _sync_background(self) -> None:
        if not self.panel_background:
            return
        try:
            bg = str(ttk.Style().lookup("TFrame", "background") or "")
            if bg and str(self.cget("background")) != bg:
                self.configure(background=bg)
        except tk.TclError:
            pass

    def _on_theme_changed(self) -> None:
        self._sync_background()
        self.redraw()

    def redraw(self) -> None:
        try:
            self.delete("all")
        except tk.TclError:
            return
        self._chips = self._layout()
        self.focus_index = min(self.focus_index, max(0, len(self._chips) - 1))
        h, _pad, _gap, margin = self._metrics()
        k = scale_factor(self)
        pal = self.palette()
        for i, c in enumerate(self._chips):
            tag = (f"chip{i}",)
            hovered = i == self.hover_index
            font = self._font
            if c.toggle:  # ghost control: text only, underlined while hovered
                c.bg = ""
                fg = pal["toggle_fg"]
                font = self._underlined if hovered else self._font
            elif c.label and c.label == self.selected:
                c.bg, fg = pal["selected_bg"], pal["selected_fg"]
                self._pill(c.x, c.y, c.w, h, fill=c.bg, tags=tag)
            else:
                state = "hover" if hovered else "normal"
                c.bg, fg = pal[f"{state}_bg"], pal[f"{state}_fg"]
                self._pill(c.x, c.y, c.w, h, fill=c.bg, outline=pal[f"{state}_border"],
                           width=max(1, round(BORDER * k)), tags=tag)
            self.create_text(c.x + c.w / 2, c.y + h / 2, text=self._text_of(c), fill=fg,
                             font=font, tags=tag)
            if self._has_focus and i == self.focus_index:
                r = RING * k
                o = (RING + RING_OFFSET) * k
                self._pill(c.x - o, c.y - o, c.w + 2 * o, h + 2 * o,
                           outline=pal["ring"], width=max(1, round(r)), fill="")
        bottom = max((c.y for c in self._chips), default=0) + h + margin
        if int(float(self.cget("height"))) != int(bottom):
            self.configure(height=int(bottom))

    def _pill(self, x: float, y: float, w: float, h: float, *, fill: str,
              outline: str = "", width: int = 0, tags: tuple[str, ...] = ()) -> None:
        """A rounded rectangle with semicircle ends, drawn as one anti-aliased image.

        Tk's own ovals and arcs are not anti-aliased on Windows, so a pill built
        from them shows stair-stepped ends and seams; Pillow draws it four times
        larger and scales it down, and the image keeps an alpha channel so it sits
        on any background.
        """
        photo = pill_photo(self, self._images, w, h, fill, outline, width)
        self.create_image(round(x), round(y), anchor="nw", image=photo, tags=tags)

    # --------------------------------------------------------------- events
    def _index_at(self, x: float, y: float) -> int | None:
        h, *_ = self._metrics()
        for i, c in enumerate(self._chips):
            slack = GHOST_PAD * scale_factor(self) if c.toggle else 0  # a text target: be generous
            if c.x - slack <= x <= c.x + c.w + slack and c.y <= y <= c.y + h:
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
        """Run the chip at ``index``: a program shortcut, or the all/less control."""
        if not (0 <= index < len(self._chips)):
            return
        chip = self._chips[index]
        if chip.toggle:
            self.expanded = not self.expanded
            self.redraw()
            return
        self.set_selected(chip.label)
        self.command(chip.label)
