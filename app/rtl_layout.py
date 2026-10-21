"""Mirror a finished Tk widget tree for right-to-left interfaces (Persian, Arabic, Hebrew).

Tk has no right-to-left layout mode: pack sides, grid columns and label anchors are given left to
right by the code that builds a window. :func:`mirror_tree` is a post-pass over a finished tree
that reflects the geometry horizontally, only when :func:`active`:

* pack slaves: ``side`` left <-> right, ``anchor`` and ``padx`` mirrored (a pack order stays, so a
  row packed left to right comes out right to left);
* grid slaves: ``column`` -> ``ncols - column - columnspan``, ``sticky`` e <-> w, ``padx``
  mirrored, and the master's column weights/minsize/pad/uniform swapped the same way;
* text widgets (labels, buttons, check and radio buttons, ``tk.Message``): ``anchor`` and
  ``justify`` mirrored. A ``ttk.Scrollbar`` packed on the right therefore moves to the left.

The interior of an Entry, Combobox, Spinbox, Text, Treeview and Canvas stays as it is (a path, a
URL or a time reads left to right; the Treeview gets its own treatment through ``displaycolumns``),
and so does everything under a widget marked with :func:`keep_ltr`; such widgets still take the
mirrored slot among their siblings, else two widgets would share one cell. Place-managed slaves,
menus and a widget created after the pass are untouched.

Every flip is an involution: applied twice it gives the original back, so a tree is mirrored
exactly once, after it is built (the pass is not idempotent). The decision is the one ``app.i18n``
takes at start-up (:func:`app.i18n.rtl_marks`); ``WTS_RTL_LAYOUT=1`` or ``0`` overrides it for a
manual try.
"""
from __future__ import annotations

import os
import tkinter as tk
from tkinter import ttk
from typing import Any

from app import i18n

#: "1" forces the mirrored layout on, "0" off; unset or anything else: ``i18n.rtl_marks()``.
ENV_OVERRIDE = "WTS_RTL_LAYOUT"
#: Set on a widget by :func:`keep_ltr`: its options and its whole subtree stay left to right.
KEEP_ATTR = "_rtl_keep"

_ANCHORS = {"w": "e", "e": "w", "nw": "ne", "ne": "nw", "sw": "se", "se": "sw"}
_SIDES = {"left": "right", "right": "left"}
_JUSTIFY = {"left": "right", "right": "left"}
_STICKY = str.maketrans("ew", "we")
#: Their contents stay left to right and the pass does not descend into them.
_KEEP_INSIDE = (tk.Entry, ttk.Entry, ttk.Combobox, tk.Spinbox, ttk.Spinbox, tk.Text, tk.Listbox,
                ttk.Treeview, tk.Canvas, tk.Menu)
#: Widgets whose ``anchor`` / ``justify`` place text (never the editable ones above).
_TEXT_WIDGETS = (tk.Label, ttk.Label, tk.Button, ttk.Button, tk.Checkbutton, ttk.Checkbutton,
                 tk.Radiobutton, ttk.Radiobutton, tk.Message, tk.Menubutton, ttk.Menubutton)


def active() -> bool:
    """True when the interface is right to left: the ``app.i18n`` decision, or the override."""
    override = os.environ.get(ENV_OVERRIDE, "").strip()
    if override in ("0", "1"):
        return override == "1"
    return i18n.rtl_marks()


def flip_side(side: str) -> str:
    """'left' <-> 'right'; 'top' and 'bottom' unchanged."""
    return _SIDES.get(side, side)


def flip_anchor(anchor: str) -> str:
    """w <-> e, nw <-> ne, sw <-> se; n, s, center and '' unchanged."""
    return _ANCHORS.get(anchor, anchor)


def flip_sticky(sticky: str) -> str:
    """Swap the e and w letters, keep n and s ('new' -> 'nwe'; Tk normalises the order)."""
    return sticky.translate(_STICKY)


def flip_justify(justify: str) -> str:
    """'left' <-> 'right'; 'center' and '' unchanged."""
    return _JUSTIFY.get(justify, justify)


def flip_padx(padx: int | tuple[int, int]) -> int | tuple[int, int]:
    """(left, right) -> (right, left); a single number unchanged."""
    if isinstance(padx, tuple) and len(padx) == 2:
        return (padx[1], padx[0])
    return padx


def keep_ltr(widget: tk.Misc) -> None:
    """Mark ``widget``: :func:`mirror_tree` leaves its options and its whole subtree alone."""
    setattr(widget, KEEP_ATTR, True)


def _keeps_ltr(widget: tk.Misc) -> bool:
    return bool(getattr(widget, KEEP_ATTR, False)) or isinstance(widget, _KEEP_INSIDE)


def _mirror_options(widget: tk.Misc) -> int:
    if not isinstance(widget, _TEXT_WIDGETS):
        return 0
    keys = widget.keys()
    changed = 0
    for option, flip in (("anchor", flip_anchor), ("justify", flip_justify)):
        if option not in keys:
            continue
        old = str(widget.cget(option))
        new = flip(old)
        if new != old:
            widget.configure({option: new})
            changed += 1
    return changed


def _mirror_pack_slaves(master: tk.Misc) -> int:
    changed = 0
    for slave in master.pack_slaves():
        info = slave.pack_info()
        slave.pack_configure({"side": flip_side(str(info["side"])),
                              "anchor": flip_anchor(str(info["anchor"])),
                              "padx": flip_padx(info["padx"])})
        changed += 1
    return changed


def _mirror_grid_slaves(master: tk.Misc) -> int:
    slaves = master.grid_slaves()
    if not slaves:
        return 0
    ncols = master.grid_size()[0]
    for slave in slaves:
        info = slave.grid_info()
        column, span = int(info["column"]), int(info["columnspan"])
        slave.grid_configure(column=ncols - column - span, sticky=flip_sticky(str(info["sticky"])),
                             padx=flip_padx(info["padx"]))
    for left in range(ncols // 2):
        right = ncols - 1 - left
        a, b = _column_options(master, left), _column_options(master, right)
        master.grid_columnconfigure(left, **b)
        master.grid_columnconfigure(right, **a)
    return len(slaves)


def _column_options(master: tk.Misc, column: int) -> dict[str, Any]:
    info = master.grid_columnconfigure(column)
    # tkinter drops None options, so an unset uniform group is written back as "".
    return {"minsize": info.get("minsize", 0), "pad": info.get("pad", 0),
            "weight": info.get("weight", 0), "uniform": info.get("uniform") or ""}


def _mirror(widget: tk.Misc) -> int:
    if _keeps_ltr(widget):
        return 0
    changed = _mirror_options(widget)
    changed += _mirror_pack_slaves(widget) + _mirror_grid_slaves(widget)
    for child in widget.winfo_children():
        changed += _mirror(child)
    return changed


def mirror_tree(widget: tk.Misc) -> int:
    """Reflect ``widget`` and everything under it horizontally when :func:`active`.

    Call it once, after the tree is built and before the window is shown. Returns the number of
    widgets whose options or geometry changed: 0 in a left-to-right interface.
    """
    if not active():
        return 0
    return _mirror(widget)


__all__ = ["ENV_OVERRIDE", "KEEP_ATTR", "active", "flip_anchor", "flip_justify", "flip_padx",
           "flip_side", "flip_sticky", "keep_ltr", "mirror_tree"]
