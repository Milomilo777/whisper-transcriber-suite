"""A row of cells that wraps onto more lines when the window is too narrow for one.

The Download tab puts three choices (Audio, Video, Output) on one line, and three
after-download toggles on another. At the 960-px minimum window, at 150 % scaling or in a
language with long words one line may not fit; instead of running off the right edge the
cells flow onto a second (or third) line, like words in a paragraph. The decision is a pure
function (``flow_rows``) so it can be tested without Tk; the widget re-runs it whenever its
own width changes and re-grids only when the line breaks move.

Geometry propagation is off and the requested size is set by hand: the width it asks for is
its widest cell, never the one-line width, so the form it sits in never asks for more than
the window (a pack-managed frame wider than its window is clipped, not shrunk, and the row
would never learn that it does not fit); the grid column with the weight gives it whatever
room the window has, and the requested height follows the current line layout.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


def flow_rows(widths: list[int], gap: int, available: int) -> list[list[int]]:
    """Indexes of ``widths`` grouped into lines, greedily, so that each line's cells plus
    the gaps between them fit in ``available`` pixels. A cell wider than the whole line
    still gets a line of its own; ``available`` <= 1 (Tk reports 1 for a widget it has not
    laid out yet) keeps one line."""
    if available <= 1 or not widths:
        return [list(range(len(widths)))]
    lines: list[list[int]] = [[]]
    used = 0
    for index, width in enumerate(widths):
        needed = width if not lines[-1] else used + gap + width
        if lines[-1] and needed > available:
            lines.append([index])
            used = width
        else:
            lines[-1].append(index)
            used = needed
    return lines


class WrapRow(ttk.Frame):
    """``row = WrapRow(parent, gap=18)``; build each cell as a child of ``row`` and
    ``row.add(cell)`` it. Cells are laid out left to right and flow onto further lines
    when the row's width cannot hold them (``line_gap`` pixels between lines). Grid the
    row with ``sticky="ew"`` in a column that may shrink (one with a weight)."""

    def __init__(self, parent: tk.Misc, *, gap: int = 18, line_gap: int = 4) -> None:
        super().__init__(parent)
        self._gap = gap
        self._line_gap = line_gap
        self._cells: list[tk.Widget] = []
        self._lines: list[list[int]] = [[]]
        self.grid_propagate(False)
        self.bind("<Configure>", lambda e: self.reflow(int(e.width)), add="+")

    @property
    def line_count(self) -> int:
        return len(self._lines)

    def add(self, cell: tk.Widget) -> None:
        self._cells.append(cell)
        self._lines = [list(range(len(self._cells)))]
        self._apply()

    def reflow(self, available: int | None = None) -> None:
        """Lay the cells out for ``available`` pixels (default: the row's current width).
        Always measured against the one-line requirement, so a row already wrapped does
        not wrap further just because it is now narrower than its first-line content."""
        if available is None:
            available = self.winfo_width()
        widths = [cell.winfo_reqwidth() for cell in self._cells]
        lines = flow_rows(widths, self._gap, available)
        if lines != self._lines:
            self._lines = lines
            self._apply()

    def _apply(self) -> None:
        for line_no, line in enumerate(self._lines):
            for column, index in enumerate(line):
                self._cells[index].grid(
                    row=line_no, column=column, sticky="w",
                    padx=(0 if column == 0 else self._gap, 0),
                    pady=(0 if line_no == 0 else self._line_gap, 0),
                )
        self._fit()
        # A cell that is a frame reports its size only once Tk has laid its children out
        # (at idle): measure again then, or the row stays 1 px tall and the line breaks
        # are computed from 1-px cells.
        self.after_idle(self._refit)

    def _fit(self) -> None:
        heights = [max((self._cells[i].winfo_reqheight() for i in line), default=0)
                   for line in self._lines]
        self.configure(
            width=max([1] + [cell.winfo_reqwidth() for cell in self._cells]),
            height=max(1, sum(heights) + self._line_gap * max(0, len(self._lines) - 1)),
        )

    def _refit(self) -> None:
        try:
            if not self.winfo_exists():
                return
            self._fit()
            if self.winfo_width() > 1:
                self.reflow()
        except tk.TclError:
            pass  # the tab is being destroyed
