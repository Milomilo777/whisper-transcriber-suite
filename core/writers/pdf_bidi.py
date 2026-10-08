"""Joined, right-to-left lines for the PDF writer.

reportlab draws characters left to right in the order it is given and
does not join Arabic-script letters. Two small PyPI packages fix that:
``arabic-reshaper`` (MIT) swaps every letter for the presentation form
that fits its place in the word (initial, medial, final, isolated, and
the lam-alef ligatures), and ``python-bidi`` (LGPL-3.0, used unmodified
as a separate package) puts a line into visual order with the Unicode
bidi algorithm (UAX #9), including bracket mirroring.

Both are optional at runtime: when either fails to import, the PDF is
still written with the letters unjoined and in logical order (the C2.56
behaviour), and one warning is logged per process.

Visual reordering works per line, so this module breaks lines itself
instead of leaving that to reportlab: a paragraph is shaped first (joins
never cross a space), broken into lines that fit the frame, and each
line is reordered on its own. The timestamp/speaker prefix is reordered
separately, as if isolated, and sits at the line's start: the left end
of a left-to-right line, the right end of a right-to-left one.

Only lines with a strong right-to-left letter (Arabic script, Hebrew)
come here; Latin, Cyrillic and CJK transcripts keep the plain path.
"""
from __future__ import annotations

import logging
import threading
import unicodedata
from typing import Callable, NamedTuple

from .base import is_rtl_text

log = logging.getLogger(__name__)

# (text, bold) pieces of one output line, left to right.
Line = list[tuple[str, bool]]
Measure = Callable[[str, bool], float]


class Engine(NamedTuple):
    reshape: Callable[[str], str]  # logical text -> joined presentation forms
    reorder: Callable[[str, str], str]  # (line, base "L"/"R") -> visual order


_ENGINE: Engine | None = None
_LOADED = False
_LOCK = threading.Lock()


def engine() -> Engine | None:
    """The shaping engine, or None when its packages are missing."""
    global _ENGINE, _LOADED
    with _LOCK:
        if not _LOADED:
            _LOADED = True
            _ENGINE = _load()
        return _ENGINE


def _load() -> Engine | None:
    try:
        import arabic_reshaper  # type: ignore[import-not-found]
        # The pure-Python algorithm (the package's __init__ still loads
        # its compiled Rust extension): the one long paired with
        # arabic-reshaper; it mirrors brackets (UAX #9 rule L4) and leaves
        # combining marks before their base (no rule L3), which is where
        # reportlab needs them to sit on the letter.
        from bidi.algorithm import get_display  # type: ignore[import-not-found]
    except (ImportError, OSError) as e:  # OSError: a native library that fails to load
        log.warning(
            "PDF: Arabic-script and Hebrew text is drawn unjoined and left "
            "to right because %s; install arabic-reshaper and python-bidi",
            e,
        )
        return None
    # Keep harakat (vowel marks): the default deletes them, which would
    # drop text from the transcript.
    reshaper = arabic_reshaper.ArabicReshaper(
        configuration={"delete_harakat": False, "support_ligatures": True}
    )

    def reorder(line: str, base: str) -> str:
        return get_display(line, base_dir=base)

    return Engine(reshape=reshaper.reshape, reorder=reorder)


def needs_bidi(text: str) -> bool:
    """True when *text* holds a strong right-to-left letter."""
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)


def _has_strong(text: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("L", "R", "AL") for ch in text)


def _clusters(word: str) -> list[str]:
    """Split *word* between letters, never before a combining mark or a
    zero-width joiner/non-joiner."""
    out: list[str] = []
    for ch in word:
        if out and (unicodedata.category(ch) in ("Mn", "Mc", "Me") or ch in "\u200c\u200d"):
            out[-1] += ch
        else:
            out.append(ch)
    return out


def _break(
    text: str, first_width: float, width: float, measure: Measure, bold: bool = False
) -> list[str]:
    """Greedy line breaks at spaces; a word wider than a whole line is
    split between letters."""
    lines: list[str] = []
    cur = ""
    limit = first_width
    for word in text.split():
        candidate = f"{cur} {word}" if cur else word
        if measure(candidate, bold) <= limit:
            cur = candidate
            continue
        if cur or (not lines and measure(word, bold) <= width):
            # A first word that only misses the prefix's room starts
            # the next line, leaving the prefix alone on the first.
            lines.append(cur)
            cur = ""
            limit = width
        if measure(word, bold) <= limit:
            cur = word
            continue
        for part in _clusters(word):
            if cur and measure(cur + part, bold) > limit:
                lines.append(cur)
                cur = ""
                limit = width
            cur += part
    if cur or not lines:
        lines.append(cur)
    return lines


def layout(
    prefix: str, body: str, width: float, measure: Measure, eng: Engine
) -> tuple[list[Line], bool]:
    """Lines of (text, bold) pieces in visual order, and whether the
    paragraph runs right to left (and is right-aligned).

    *prefix* is drawn bold; *measure(text, bold)* gives a width in the
    same unit as *width*.
    """
    rtl = is_rtl_text(body) if _has_strong(body) else is_rtl_text(prefix)
    base = "R" if rtl else "L"
    shaped_prefix = eng.reshape(prefix) if prefix else ""
    shaped_body = eng.reshape(body)
    lines: list[Line] = []
    first_width = width
    if shaped_prefix:
        room = width - measure(shaped_prefix, True) - measure(" ", False)
        if room > 0:
            first_width = room
        else:
            # A prefix as wide as the line (a very long speaker name)
            # gets lines of its own; the body starts on the next line.
            lines = [
                [(eng.reorder(part, base), True)]
                for part in _break(shaped_prefix, width, width, measure, bold=True)
            ]
            shaped_prefix = ""
    for i, chunk in enumerate(_break(shaped_body, first_width, width, measure)):
        line: Line = [(eng.reorder(chunk, base), False)]
        if i == 0 and shaped_prefix:
            head = (eng.reorder(shaped_prefix, base), True)
            line = line + [(" ", False), head] if rtl else [head, (" ", False)] + line
        lines.append(line)
    return lines, rtl
