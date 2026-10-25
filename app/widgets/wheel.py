"""Mouse-wheel binding that lives only while the pointer is inside a subtree.

``<Leave>`` fires on a widget with detail ``Inferior`` when the pointer
moves onto one of the widget's OWN children, and between siblings inside
the subtree — a leave handler that unconditionally ``unbind_all`` kills
the wheel exactly over the content, the place the pointer usually is.
``app/widgets/notice.py`` pioneered the ``winfo_containing`` guard for
hover; this module is the same idea for scrolling panels.
"""
from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

_SEQUENCES = ("<MouseWheel>", "<Button-4>", "<Button-5>")


def pointer_inside(widget: tk.Misc) -> bool:
    """True when the pointer is over *widget* or one of its descendants."""
    try:
        x, y = widget.winfo_pointerxy()
        under = widget.winfo_containing(x, y)
    except tk.TclError:
        return False
    path = str(widget)
    found = str(under) if under is not None else ""
    return found == path or found.startswith(path + ".")


def bind_wheel_while_inside(
    canvas: tk.Canvas,
    scroll: Callable[["tk.Event[Any]"], None],
    *anchors: tk.Misc,
) -> None:
    """``bind_all`` the wheel sequences while the pointer is inside *canvas*.

    *scroll* receives every wheel event (all three sequences); it decides
    direction itself from ``event.delta`` / ``event.num``. *anchors* are
    additional widgets (the scrolled content frame and its like) whose
    ``<Enter>``/``<Leave>`` crossings must not drop the binding; the guard
    always tests the *canvas* subtree, which contains them.
    """
    def enter(_e: Any) -> None:
        for seq in _SEQUENCES:
            canvas.bind_all(seq, scroll)

    def leave(_e: Any) -> None:
        # A Leave onto a child of the subtree (detail Inferior) or between
        # its siblings is not leaving: keep the wheel until the pointer is
        # truly outside the canvas.
        if pointer_inside(canvas):
            return
        for seq in _SEQUENCES:
            canvas.unbind_all(seq)

    for widget in (canvas, *anchors):
        widget.bind("<Enter>", enter)
        widget.bind("<Leave>", leave)
