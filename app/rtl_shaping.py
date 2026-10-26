"""Display-only shaping of right-to-left text for Tk on Linux.

Tk 8.6 on X11 neither joins Arabic-script letters nor applies the Unicode bidi algorithm (Tk
ticket 1b81ff43a2, fixed only in Tk 9.1 with HarfBuzz): Persian and Arabic come out unjoined and
reversed, Hebrew reversed. Windows and macOS draw such text natively and never come here.

:func:`visual` turns logical text into what a Tk label must be given to look right: every letter
is replaced by its presentation form (arabic-reshaper) and every line is put in visual order
(python-bidi), the same engine the PDF writer uses (``core.writers.pdf_bidi``). The result is
for DISPLAY only, in labels, buttons, menus, tabs, tooltips, message boxes and result lists. It is
never given to an Entry, Combobox or Text the user types in, and never stored, compared, copied
or saved: those keep the logical order. ``app.i18n`` calls it once, at the single place where
a translated text is finished, and ``app.theme.bidi_display.ltr_base`` for names shown in lists.

A text is never shaped twice. Reordering twice would put the letters back, so every result is
remembered; :func:`visual` returns a remembered result (or a line that already holds Arabic
presentation forms) unchanged, and :func:`logical` gives back the text a result came from (for
``plain()``, the log file and the clipboard, and for a shaped value inside another text).
Wrapped labels are the known limit: Tk breaks a long visual line at its width from the left, so
a label long enough to wrap shows its lines in the wrong order.
"""
from __future__ import annotations

import sys
import threading
import unicodedata
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.writers.pdf_bidi import Engine

#: Platforms whose Tk cannot shape or order right-to-left text itself.
SHAPED_PLATFORMS: frozenset[str] = frozenset({"linux"})

# Arabic Presentation Forms-A and -B: what arabic-reshaper writes. A line holding one is already
# shaped (the catalogs and the transcripts never contain them).
_PRESENTATION_FORMS = (range(0xFB50, 0xFE00), range(0xFE70, 0xFF00))
_REMEMBERED = 20000  # results kept for logical(); far more than the interface has texts

_LOCK = threading.Lock()
_VISUAL_TO_LOGICAL: OrderedDict[str, str] = OrderedDict()
_CACHE: dict[tuple[str, str], str] = {}


def _engine() -> "Engine | None":
    """The shaping engine of the PDF writer (None when its packages are missing)."""
    from core.writers import pdf_bidi
    return pdf_bidi.engine()


def available() -> bool:
    """True when arabic-reshaper and python-bidi can be imported."""
    return _engine() is not None


def applies() -> bool:
    """True on a platform that needs shaping, with the engine installed."""
    return sys.platform in SHAPED_PLATFORMS and available()


def _has_rtl_letter(text: str) -> bool:
    return any(unicodedata.bidirectional(ch) in ("R", "AL") for ch in text)


def _is_shaped(line: str) -> bool:
    return any(ord(ch) in r for ch in line for r in _PRESENTATION_FORMS)


def _remember(shaped: str, logical: str) -> None:
    with _LOCK:
        _VISUAL_TO_LOGICAL[shaped] = logical
        _VISUAL_TO_LOGICAL.move_to_end(shaped)
        while len(_VISUAL_TO_LOGICAL) > _REMEMBERED:
            _VISUAL_TO_LOGICAL.popitem(last=False)
        if len(_CACHE) > _REMEMBERED:
            _CACHE.clear()


# Bracket pairs (Bidi_Paired_Bracket) for the pair fix below: the three ASCII pairs and some more,
# so a line can hold up to twelve pairs.
_OPENERS = "([{⟦⟨⟪⦃⦅⦇⦉⦋"
_CLOSERS = ")]}⟧⟩⟫⦄⦆⦈⦊⦌"
_LRM, _RLM = "‎", "‏"
_ZWNJ = "‌"


def _bracket_pairs(line: str) -> tuple[list[tuple[int, int]], set[int]]:
    """(opening index, closing index) of the matched ASCII-style brackets of *line*, and the
    indexes of every other bracket (unmatched ones)."""
    stack: list[tuple[int, int]] = []  # (kind, index)
    pairs: list[tuple[int, int]] = []
    matched: set[int] = set()
    for i, ch in enumerate(line):
        if ch in _OPENERS:
            stack.append((_OPENERS.index(ch), i))
        elif ch in _CLOSERS:
            kind = _CLOSERS.index(ch)
            for depth in range(len(stack) - 1, -1, -1):
                if stack[depth][0] == kind:
                    pairs.append((stack[depth][1], i))
                    matched.update((stack[depth][1], i))
                    del stack[depth:]
                    break
    loose = {i for i, ch in enumerate(line) if (ch in _OPENERS or ch in _CLOSERS) and i not in matched}
    return pairs, loose


def _pair_directions(shaped: str, pairs: list[tuple[int, int]], loose: set[int]) -> list[bool] | None:
    """For each pair, True when the Unicode bidi algorithm (UAX #9 rule N0) makes it left to right.

    python-bidi's pure-Python algorithm lacks rule N0 and so mirrors the closing bracket of
    "report.txt (12 GB)" at the end of a right-to-left line. Its Rust algorithm has N0 but never
    mirrors. So the Rust one answers the question here: each pair is given characters no other pair
    has, and the pair is left to right when its opening character comes out left of its closing one.
    """
    if not pairs or len(pairs) > len(_OPENERS):
        return None
    try:
        from bidi import get_display as rust_display  # type: ignore[import-not-found]
    except (ImportError, OSError):
        return None
    probe = list(shaped)
    for i in loose:
        probe[i] = "!"  # a neutral that is no bracket
    for m, (i, j) in enumerate(pairs):
        probe[i], probe[j] = _OPENERS[m], _CLOSERS[m]
    out = rust_display("".join(probe), base_dir="R")
    if not isinstance(out, str):
        out = out.decode("utf-8")
    return [out.find(_OPENERS[m]) < out.find(_CLOSERS[m]) for m in range(len(pairs))]


def _order(engine: "Engine", shaped: str, base: str) -> str:
    """*shaped* in visual order with mirrored brackets, brackets paired as UAX #9 N0 says."""
    forced = shaped
    if base == "R":
        pairs, loose = _bracket_pairs(shaped)
        directions = _pair_directions(shaped, pairs, loose)
        if directions is not None:
            marks: dict[int, str] = {}
            for (i, j), is_ltr in zip(pairs, directions):
                mark = _LRM if is_ltr else _RLM
                marks[i], marks[j] = mark, mark
            # A mark outside each bracket makes the algorithm resolve it as N0 decided
            # (before an opening one, after a closing one); they are removed again below.
            forced = "".join(
                (marks[i] + ch if ch in _OPENERS else ch + marks[i]) if i in marks else ch
                for i, ch in enumerate(shaped)
            )
    out = engine.reorder(forced, base)
    return out.replace(_LRM, "").replace(_RLM, "").replace(_ZWNJ, "")


def _shape_line(line: str, base: str) -> str:
    # A trailing carriage return (CRLF text) stays at the end of its line.
    body, tail = (line[:-1], "\r") if line.endswith("\r") else (line, "")
    if not body or not _has_rtl_letter(body) or _is_shaped(body):
        return line
    engine = _engine()
    if engine is None:
        return line
    with _LOCK:
        if body in _VISUAL_TO_LOGICAL:
            return line
        cached = _CACHE.get((body, base))
    if cached is not None:
        return cached + tail
    out = _order(engine, engine.reshape(body), base)
    if out != body:
        _remember(out, body)
    with _LOCK:
        _CACHE[(body, base)] = out
    return out + tail


def visual(text: str, base: str = "R") -> str:
    """*text* in the form a Tk label needs on Linux: joined letters, visual order, per line.

    *base* is the paragraph direction, "R" (an interface text of a right-to-left language) or
    "L" (a name inside an English sentence). Lines without a right-to-left letter, lines already
    shaped and everything when the engine is missing are returned as they are.
    """
    if not text or not _has_rtl_letter(text):
        return text
    if "\n" not in text:
        return _shape_line(text, base)
    return "\n".join(_shape_line(line, base) for line in text.split("\n"))


def logical(text: str) -> str:
    """The text *text* was shaped from; *text* itself when :func:`visual` did not make it."""
    if not text:
        return text
    with _LOCK:
        known = _VISUAL_TO_LOGICAL
        if "\n" not in text:
            body, tail = (text[:-1], "\r") if text.endswith("\r") else (text, "")
            return known.get(body, body) + tail
        out = []
        for line in text.split("\n"):
            body, tail = (line[:-1], "\r") if line.endswith("\r") else (line, "")
            out.append(known.get(body, body) + tail)
    return "\n".join(out)
