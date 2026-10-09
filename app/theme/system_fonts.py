"""The macOS system font for the UI (card C2.73).

sv_ttk draws every ttk widget in named fonts whose families are Windows-only ("Segoe UI Variable
Static Text", ...). Tk on macOS happens to substitute the system font for an unknown family
(``tools/mac_native_probe.py`` on macOS 13 / Tk 8.6.16: a font asked for "Segoe UI Variable Text"
draws as ``.AppleSystemUIFont``), but a substitution nobody asked for is not a design: on Aqua the
theme fonts name the system font, ``.AppleSystemUIFont``, directly. It is the family behind
``TkDefaultFont`` on macOS and the one macOS draws per script itself: the same probe shows a
Persian or Arabic character in ``.SF Arabic``, Han in ``.PingFang SC``, Hangul in
``.Apple SD Gothic NeoI``, Thai in ``.ThonburiUI``. So the per-script fonts of
``app.theme.script_fonts`` stay what they were, Windows-only.

Sizes are left as sv_ttk made them (pixels, grown with the display scale by
``script_fonts.scale_theme_fonts``); only the family and, for the "Semibold" theme fonts, the
weight change. On every other system nothing here changes any font.
"""
from __future__ import annotations

import logging
import tkinter as tk
from typing import Any

from app import mac_native

logger = logging.getLogger(__name__)

#: The system UI font on macOS (what ``TkDefaultFont`` uses there).
SYSTEM_UI_FAMILY = ".AppleSystemUIFont"

# sv_ttk's named fonts (sv.tcl creates them once, in pixels). The ones whose Windows family is a
# "Semibold" face become bold: macOS has no family to name for that weight.
_THEME_FONTS: dict[str, bool] = {
    "SunValleyCaptionFont": False,
    "SunValleyBodyFont": False,
    "SunValleyBodyStrongFont": True,
    "SunValleyBodyLargeFont": False,
    "SunValleySubtitleFont": True,
    "SunValleyTitleFont": True,
    "SunValleyTitleLargeFont": True,
    "SunValleyDisplayFont": True,
}


def apply(root: Any) -> bool:
    """Give sv_ttk's named fonts the system family on macOS; True when a font changed.

    Safe to call after every theme switch: a font already right is left alone. A no-op, without a
    single Tcl call, where Tk is not Aqua.
    """
    if not mac_native.is_aqua(root):
        return False
    names = set(root.tk.splitlist(root.tk.call("font", "names")))
    changed = False
    for name, bold in _THEME_FONTS.items():
        if name not in names:
            continue
        weight = "bold" if bold else "normal"
        try:
            family = str(root.tk.call("font", "configure", name, "-family"))
            current = str(root.tk.call("font", "configure", name, "-weight"))
            if family == SYSTEM_UI_FAMILY and current == weight:
                continue
            root.tk.call("font", "configure", name, "-family", SYSTEM_UI_FAMILY, "-weight", weight)
        except tk.TclError as exc:
            logger.warning("Could not give %s the system font: %s", name, exc)
            continue
        changed = True
    return changed


def ui_font(widget: Any, family: str, size: int, style: str = "") -> tuple[Any, ...]:
    """A Tk font tuple for a hard-coded UI font: the system font on macOS, else exactly as given.

    ``family`` is the Windows name the call site used ("Segoe UI", "Segoe UI Semibold"); a family
    that ends in "Semibold" becomes the bold system font. Elsewhere the result is
    ``(family, size)`` or ``(family, size, style)``, the tuples the call sites had before.
    """
    if not mac_native.is_aqua(widget):
        return (family, size, style) if style else (family, size)
    words = style.split()
    if family.endswith("Semibold") and "bold" not in words:
        words.insert(0, "bold")
    return (SYSTEM_UI_FAMILY, size, " ".join(words)) if words else (SYSTEM_UI_FAMILY, size)
