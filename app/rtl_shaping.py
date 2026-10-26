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
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from core.writers.pdf_bidi import Engine

#: Platforms whose Tk cannot shape or order right-to-left text itself.
SHAPED_PLATFORMS: frozenset[str] = frozenset({"linux"})

# The letters of Arabic Presentation Forms-A and -B: what arabic-reshaper writes. A line holding
# one that visual() did not make is left alone (the catalogs and transcripts never contain them).
# Not included: the ornate parentheses U+FD3E/FD3F, the noncharacters U+FDD0..FDEF, the rial sign
# U+FDFC (a currency symbol real text uses) and the byte order mark U+FEFF.
_PRESENTATION_FORMS = (range(0xFB50, 0xFD3E), range(0xFD40, 0xFDD0), range(0xFDF0, 0xFDFC),
                       range(0xFE70, 0xFEFD))
_REMEMBERED = 20000  # results kept for logical(); far more than the interface has texts
# Hebrew is only reversed, so a reversed text can equal a real text (the reversal of "HMR" is "RMH").
# When the caller does not know that a text is an earlier result, a Hebrew result shorter than this
# is never taken for one; Arabic results are unmistakable (presentation forms) and count at any
# length. A caller that knows (plain(), the tray, display(), status clipping) accepts any exact
# whole-string match and, for segments inside a larger string, ones of at least _TRUSTED_SEGMENT.
_MIN_HEBREW_SEGMENT = 5
_TRUSTED_SEGMENT = 3

_LOCK = threading.Lock()
_VISUAL_TO_LOGICAL: OrderedDict[str, str] = OrderedDict()
_BY_FIRST_CHAR: dict[str, set[str]] = {}  # the keys above by their first character
_CACHE: dict[tuple[str, str, bool, bool], str] = {}


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
    if not shaped or shaped == logical:  # an empty key would match everywhere
        return
    with _LOCK:
        _VISUAL_TO_LOGICAL[shaped] = logical
        _VISUAL_TO_LOGICAL.move_to_end(shaped)
        _BY_FIRST_CHAR.setdefault(shaped[0], set()).add(shaped)
        while len(_VISUAL_TO_LOGICAL) > _REMEMBERED:
            old, _ = _VISUAL_TO_LOGICAL.popitem(last=False)
            keys = _BY_FIRST_CHAR.get(old[0])
            if keys is not None:
                keys.discard(old)
                if not keys:
                    del _BY_FIRST_CHAR[old[0]]
        if len(_CACHE) > _REMEMBERED:
            _CACHE.clear()


def _recover(text: str, min_hebrew: int = _MIN_HEBREW_SEGMENT) -> str:
    """*text* with every shaped segment that :func:`visual` made swapped back to its logical text.

    Longest segment first. An Arabic segment is unmistakable (presentation forms); a Hebrew one
    (only reversed) must have at least *min_hebrew* characters and stand between non-letters, so
    that a short real word that equals some reversed word is not taken for one.
    """
    chars = set(text)
    with _LOCK:  # a snapshot of the candidates: the keys that start with a character of the text
        found = [(k, _VISUAL_TO_LOGICAL[k]) for c in chars for k in _BY_FIRST_CHAR.get(c, ())
                 if len(k) <= len(text)]
    hits = sorted((kv for kv in found if kv[0] in text), key=lambda kv: len(kv[0]), reverse=True)
    if not hits:
        return text
    pieces: list[tuple[str, bool]] = [(text, False)]  # (text, already logical)
    for key, logical_text in hits:
        arabic = _is_shaped(key)
        if not arabic and len(key) < min_hebrew:
            continue
        nxt: list[tuple[str, bool]] = []
        for part, done in pieces:
            if done or key not in part:
                nxt.append((part, done))
                continue
            emitted = scan = 0
            while True:
                i = part.find(key, scan)
                if i < 0:
                    break
                j = i + len(key)
                if not arabic and ((i > 0 and part[i - 1].isalpha())
                                   or (j < len(part) and part[j].isalpha())):
                    scan = i + 1
                    continue
                if i > emitted:
                    nxt.append((part[emitted:i], False))
                nxt.append((logical_text, True))
                emitted = scan = j
            if emitted < len(part):
                nxt.append((part[emitted:], False))
        pieces = nxt
    return "".join(p for p, _done in pieces)


# Bracket pairs (Bidi_Paired_Bracket) for the pair fix below: the three ASCII pairs and some more,
# so a line can hold up to twelve pairs. Built from code points: invisible or look-alike characters
# never sit in this source.
_OPENERS = "([{" + "".join(chr(c) for c in (0x27E6, 0x27E8, 0x27EA, 0x2983, 0x2985, 0x2987, 0x2989, 0x298B))
_CLOSERS = ")]}" + "".join(chr(c) for c in (0x27E7, 0x27E9, 0x27EB, 0x2984, 0x2986, 0x2988, 0x298A, 0x298C))
_LRM, _RLM = chr(0x200E), chr(0x200F)
_ZWNJ = chr(0x200C)


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


_RUST: list[Any] = []  # [function or None], filled on first use


def _rust_display() -> Any:
    """python-bidi's Rust ``get_display`` (None when it cannot be imported), imported once."""
    if not _RUST:
        try:
            from bidi import get_display  # type: ignore[import-not-found]
        except (ImportError, OSError):
            get_display = None
        _RUST.append(get_display)
    return _RUST[0]


def _pair_directions(shaped: str, pairs: list[tuple[int, int]], loose: set[int]) -> list[bool] | None:
    """For each pair, True when the Unicode bidi algorithm (UAX #9 rule N0) makes it left to right.

    python-bidi's pure-Python algorithm lacks rule N0 and so mirrors the closing bracket of
    "report.txt (12 GB)" at the end of a right-to-left line. Its Rust algorithm has N0 but never
    mirrors. So the Rust one answers the question here: each pair is given characters no other pair
    has, and the pair is left to right when its opening character comes out left of its closing one.
    """
    if not pairs or len(pairs) > len(_OPENERS):
        return None
    rust_display = _rust_display()
    if rust_display is None:
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


def _split_cr(line: str) -> tuple[str, str]:
    """A line and its trailing carriage return (CRLF text keeps it at the end of the line)."""
    return (line[:-1], "\r") if line.endswith("\r") else (line, "")


def _is_result(body: str, any_length: bool = False) -> bool:
    """True when *body* is a whole line that :func:`visual` made. Unless *any_length* (the caller
    knows it is shaped text), a short Hebrew line is not taken for one: it may be real text."""
    with _LOCK:
        known = body in _VISUAL_TO_LOGICAL
    return known and (any_length or len(body) >= _MIN_HEBREW_SEGMENT or _is_shaped(body))


def _shape_line(line: str, base: str, logical_input: bool = False, trusted: bool = False) -> str:
    body, tail = _split_cr(line)
    if not body or not _has_rtl_letter(body):
        return line
    engine = _engine()
    if engine is None:
        return line
    if not logical_input and _is_result(body, trusted):  # a line visual() made: never shaped twice
        return line
    key = (body, base, logical_input, trusted)
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached + tail
    # Shaped segments inside the line (a name from ltr_base, a sentence of _()) go back to their
    # logical text, so the whole line is shaped once, in one reading order.
    source = body if logical_input else _recover(body, _TRUSTED_SEGMENT if trusted else _MIN_HEBREW_SEGMENT)
    if _is_shaped(source):  # presentation forms visual() did not make: cannot be put right
        return line
    out = _order(engine, engine.reshape(source), base)
    _remember(out, source)
    with _LOCK:
        _CACHE[key] = out
    return out + tail


def visual(text: str, base: str = "R", logical_input: bool = False, trusted: bool = False) -> str:
    """*text* in the form a Tk label needs on Linux: joined letters, visual order, per line.

    *base* is the paragraph direction, "R" (an interface text of a right-to-left language) or
    "L" (a name inside an English sentence). Lines without a right-to-left letter, a line that is
    already a result of this function, and everything when the engine is missing are returned as
    they are. A line that holds results inside other text (``"  " + _("x")``) is shaped again as
    a whole, from the logical text of its parts. ``logical_input=True`` says the caller knows
    *text* is logical (a catalog translation): nothing in it is taken for an earlier result.
    ``trusted=True`` says *text* is made of earlier results (UI text joined from translated
    parts): any exact result, and shorter Hebrew segments, are taken for results.
    """
    if not text or not _has_rtl_letter(text):
        return text
    if "\n" not in text:
        return _shape_line(text, base, logical_input, trusted)
    return "\n".join(_shape_line(line, base, logical_input, trusted) for line in text.split("\n"))


def _logical_line(line: str, trusted: bool = False) -> str:
    body, tail = _split_cr(line)
    if _is_result(body, any_length=True):  # the caller passes shaped UI text
        with _LOCK:
            return _VISUAL_TO_LOGICAL[body] + tail
    if not body or not _has_rtl_letter(body):
        return line
    return _recover(body, _TRUSTED_SEGMENT if trusted else _MIN_HEBREW_SEGMENT) + tail


def logical(text: str, trusted: bool = False) -> str:
    """The logical text of *text*: every segment :func:`visual` made, whole or inside a larger
    string, is swapped back; everything else is kept as it is.

    A whole line that is an earlier result is swapped back at any length. Inside a larger line
    a Hebrew segment needs five characters, or three with ``trusted=True`` (the caller knows the
    line is UI text made of earlier results)."""
    if not text:
        return text
    if "\n" not in text:
        return _logical_line(text, trusted)
    return "\n".join(_logical_line(line, trusted) for line in text.split("\n"))


# --- window titles ------------------------------------------------------------------------------------

_RESTORE: list[Callable[[], None]] = []


def install_title_hook(wm: Any = None, dialog: Any = None) -> Callable[[], None]:
    """Make window titles take logical text; returns a function that undoes the hook.

    The window manager draws a title itself, with its own joining and bidi algorithm, so a
    shaped title would be reordered a second time. ``wm`` (default ``tkinter.Wm``) gets a
    ``wm_title`` / ``title`` that turns a shaped text into logical text; ``dialog`` (default
    ``tkinter.commondialog.Dialog``, the base of the message and file dialogs) does the same for
    its ``title`` option. Asking for the title (no argument) is unchanged. Installing twice is a
    no-op. The text inside a dialog is drawn by Tk and stays shaped.
    """
    import tkinter as tk
    from tkinter import commondialog

    wm = wm or tk.Wm
    dialog = dialog or commondialog.Dialog
    undo: list[Callable[[], None]] = []
    if not wm.__dict__.get("_wts_logical_title"):
        orig_title, orig_wm_title = wm.__dict__.get("title"), wm.__dict__.get("wm_title")
        base_title = wm.wm_title

        def wm_title(self: Any, string: Any = None) -> Any:
            return base_title(self, logical(string) if isinstance(string, str) else string)

        wm.wm_title = wm.title = wm_title
        wm._wts_logical_title = True

        def undo_wm() -> None:
            for name, old in (("title", orig_title), ("wm_title", orig_wm_title)):
                if old is None:
                    delattr(wm, name)
                else:
                    setattr(wm, name, old)
            del wm._wts_logical_title

        undo.append(undo_wm)
    if not dialog.__dict__.get("_wts_logical_title"):
        orig_show = dialog.__dict__.get("show")
        base_show = dialog.show

        def show(self: Any, **options: Any) -> Any:
            if isinstance(options.get("title"), str):
                options["title"] = logical(options["title"])
            held = getattr(self, "options", None)
            if isinstance(held, dict) and isinstance(held.get("title"), str):
                held["title"] = logical(held["title"])
            return base_show(self, **options)

        dialog.show = show
        dialog._wts_logical_title = True

        def undo_dialog() -> None:
            if orig_show is None:
                del dialog.show
            else:
                dialog.show = orig_show
            del dialog._wts_logical_title

        undo.append(undo_dialog)

    def restore() -> None:
        while undo:
            undo.pop()()

    return restore


def install_title_hook_once() -> None:
    """:func:`install_title_hook` on the real Tk classes, once per process."""
    if _RESTORE:
        return
    try:
        _RESTORE.append(install_title_hook())
    except ImportError:  # no tkinter: no window titles either
        return


def uninstall_title_hook() -> None:
    """Undo :func:`install_title_hook_once` (tests)."""
    while _RESTORE:
        _RESTORE.pop()()
