"""Swap the theme-following colours of existing widgets when the Light/Dark theme changes.

sv_ttk restyles the ttk widgets, but a colour a widget was given (``foreground=themed(...)``, a
Treeview or Text tag's tint) stays what it was. ``apply`` records the new theme for
``tokens.themed`` and walks the widget tree once: every colour that is a light-theme token with a
dark variant (``tokens.DARK_VARIANTS``), or such a variant, becomes the one of the new theme.
Colours outside that table are left alone.

Not reached: ttk styles (they belong to a theme; whoever configures a custom style with a themed
colour configures it again after a switch, like ``live_tab.apply_theme``), menu entries, Canvas
and Listbox items.
"""
from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Iterator

from app.theme import tokens

logger = logging.getLogger(__name__)

_WIDGET_OPTIONS = ("foreground", "background")
_TAG_OPTIONS = ("foreground", "background")


def _swap(value: object, theme: str) -> str | None:
    """The colour that replaces ``value`` on ``theme``, or None to keep it."""
    colour = str(value).strip().lower()
    if not colour.startswith("#"):
        return None
    table = tokens.LIGHT_VARIANTS if theme == "light" else tokens.DARK_VARIANTS
    new = table.get(colour)
    return new if new is not None and new != colour else None


def _widgets(root: tk.Misc) -> Iterator[tk.Misc]:
    stack: list[tk.Misc] = [root]
    while stack:
        widget = stack.pop()
        yield widget
        try:
            stack.extend(widget.winfo_children())
        except tk.TclError:
            continue


def _recolour_widget(widget: tk.Misc, theme: str) -> int:
    changed = 0
    for option in _WIDGET_OPTIONS:
        try:
            new = _swap(widget.cget(option), theme)
            if new is not None:
                widget.configure({option: new})
                changed += 1
        except (tk.TclError, ValueError):
            continue  # the widget has no such option
    return changed


def _recolour_tags(widget: tk.Misc, theme: str) -> int:
    """Treeview and Text tags (row tints, confidence colours, links)."""
    changed = 0
    try:
        tags = widget.tk.splitlist(widget.tk.call(widget._w, "tag", "names"))  # type: ignore[attr-defined]
    except tk.TclError:
        return 0
    is_tree = widget.winfo_class() == "Treeview"
    for tag in tags:
        for option in _TAG_OPTIONS:
            try:
                if is_tree:
                    value = widget.tk.call(widget._w, "tag", "configure", tag, f"-{option}")  # type: ignore[attr-defined]
                else:
                    value = widget.tk.call(widget._w, "tag", "cget", tag, f"-{option}")  # type: ignore[attr-defined]
                new = _swap(value, theme)
                if new is not None:
                    widget.tk.call(widget._w, "tag", "configure", tag, f"-{option}", new)  # type: ignore[attr-defined]
                    changed += 1
            except tk.TclError:
                continue
    return changed


def recolour(root: tk.Misc, theme: str) -> int:
    """Give every widget under ``root`` (Toplevels included) the colours of ``theme``.

    Returns how many colours changed.
    """
    resolved = "light" if theme == "light" else "dark"
    changed = 0
    for widget in _widgets(root):
        changed += _recolour_widget(widget, resolved)
        if widget.winfo_class() in ("Treeview", "Text"):
            changed += _recolour_tags(widget, resolved)
    return changed


def apply(root: tk.Misc, theme: str) -> int:
    """Call after every ``sv_ttk.set_theme``: record the theme, then recolour existing widgets."""
    tokens.set_theme(theme)
    changed = recolour(root, theme)
    logger.debug("Theme %s: %d widget colours swapped", theme, changed)
    return changed
