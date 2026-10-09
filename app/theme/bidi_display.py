"""Left-to-right base direction for file names and result lines on macOS.

Tk on macOS (aqua) draws text with CoreText, which applies the Unicode bidi algorithm itself and
takes the paragraph direction from the FIRST STRONG letter of the string (measured with Tk 8.6.16
on macOS 13: Label, Entry, Text and Treeview alike). Arabic-script text is joined and ordered
correctly; the trouble is the base direction of a string that starts with an Arabic-script letter
(after neutral characters such as a bullet or a check mark): it becomes right to left, so
"<Persian name>.wav" is drawn as "wav.<Persian name>" and the "bullet, space" in front of the name
jumps to the right end of the line. Tk on Windows always uses a left-to-right base, so the same
string reads naturally there, and the application layout is left to right.

``ltr_base`` puts one invisible LEFT-TO-RIGHT MARK in front of such a string, on macOS only. That
restores the Windows reading order without reordering or re-shaping anything (the platform does
both already; python-bidi's visual order would be reordered a second time). It is for display
strings only: never pass it data that is stored, compared, copied, edited or saved. Transcript
lines keep the first-strong direction on purpose: it is what a Persian sentence with a Latin word
in it needs.
"""
from __future__ import annotations

import sys
import unicodedata

LRM = chr(0x200E)  # LEFT-TO-RIGHT MARK: a strong left-to-right character of zero width


def is_aqua() -> bool:
    """True on macOS, where Tk draws with CoreText (tests patch this)."""
    return sys.platform == "darwin"


def ltr_base(text: str) -> str:
    """*text* for a label or a Treeview cell: left-to-right base direction on macOS.

    Returns *text* unchanged off macOS and when its first strong character is not right to left
    (a string that already starts with the mark counts as left to right, so the result is stable
    when applied twice).
    """
    if not is_aqua():
        return text
    for ch in text:
        kind = unicodedata.bidirectional(ch)
        if kind == "L":
            return text
        if kind in ("R", "AL"):
            return LRM + text
    return text
