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

A text is never shaped twice, and never taken for shaped by its look. Reordering twice would put
the letters back, and Hebrew is only reversed, so a reversed word can equal a real word (the raw
name of a speaker or a file). What :func:`visual` returns is therefore a :class:`Shaped`: a ``str``
that carries its logical text. :func:`logical` reads it back from the object, ``+`` between a
Shaped and any text keeps track of both parts, and :func:`visual` of a joined text shapes the
logical whole once. Plain ``str`` (raw data) is always taken for logical text. Arabic results,
which are unmistakable (presentation forms), are also remembered by text, so an f-string or
``join`` around one can still be recovered; Hebrew results are not. Texts joined by anything but
``+`` (f-strings, ``str.join``, ``%``) lose a Hebrew part's identity: build them with ``+`` or
let ``_()`` place the parts.

Wrapped labels are the known limit: Tk breaks a long visual line at its width from the left, so
a label long enough to wrap shows its lines in the wrong order.
"""
from __future__ import annotations

import sys
import threading
import unicodedata
from collections import OrderedDict
from collections.abc import Callable, Iterable
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
_REMEMBERED = 20000  # Arabic results kept by text for logical(); far more than the interface has

_LOCK = threading.Lock()
_VISUAL_TO_LOGICAL: OrderedDict[str, str] = OrderedDict()
_BY_FIRST_CHAR: dict[str, set[str]] = {}  # the keys above by their first character
# Whole shaped Hebrew lines (they only look reversed, so they can equal real text) -> logical line.
# Read only by to_logical(), for text that leaves the screen; never for placeholders or display().
_HEBREW_TO_LOGICAL: OrderedDict[str, str] = OrderedDict()
_CACHE: dict[tuple[str, str, bool], tuple[str, str]] = {}  # (line, base, logical_input) -> (shown, logical)


class Shaped(str):
    """A display-shaped text that knows the logical text it came from.

    It is a ``str`` (Tk, ``==``, hashing and slicing work as usual); ``logical`` is the text a
    user would type or copy. ``+`` with another text gives a Shaped with ``composed`` set, whose
    string is the plain concatenation (wrong reading order) and whose logical text is the
    concatenation of the logical parts: :func:`visual` and ``i18n.display`` shape it again, once.
    """

    logical: str
    composed: bool

    def __new__(cls, shown: str, logical: str, composed: bool = False) -> "Shaped":
        obj = super().__new__(cls, shown)
        obj.logical = logical
        obj.composed = composed
        return obj

    def __getnewargs__(self) -> tuple[str, str, bool]:  # copy and pickle
        return (str(self), self.logical, self.composed)

    def __add__(self, other: str) -> "Shaped":  # type: ignore[override]
        if not isinstance(other, str):
            return NotImplemented
        return Shaped(str.__add__(self, other), self.logical + logical(other), True)

    def __radd__(self, other: str) -> "Shaped":
        if not isinstance(other, str):
            return NotImplemented
        return Shaped(str.__add__(other, self), logical(other) + self.logical, True)


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


def _remember(shaped: str, logical_text: str) -> None:
    """Remember an Arabic result by its text (a key holds presentation forms, so it cannot be
    real text)."""
    if not shaped or shaped == logical_text or not _is_shaped(shaped):
        return
    with _LOCK:
        _VISUAL_TO_LOGICAL[shaped] = logical_text
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


def _remember_hebrew(shaped: str, logical_text: str) -> None:
    """Remember a whole Hebrew result line by its text, for :func:`to_logical` only."""
    if not shaped or shaped == logical_text:
        return
    with _LOCK:
        _HEBREW_TO_LOGICAL[shaped] = logical_text
        _HEBREW_TO_LOGICAL.move_to_end(shaped)
        while len(_HEBREW_TO_LOGICAL) > _REMEMBERED:
            _HEBREW_TO_LOGICAL.popitem(last=False)


def _lookup_result(body: str) -> str | None:
    """The logical text of *body* when it is an Arabic result remembered by text (one lock, one
    ``get``: another thread may evict it at any time)."""
    with _LOCK:
        return _VISUAL_TO_LOGICAL.get(body)


def _recover(text: str) -> str:
    """*text* with every remembered Arabic result inside it swapped back to its logical text.

    Longest result first. Only results made of presentation forms are remembered, so nothing
    that is real text can match.
    """
    chars = set(text)
    with _LOCK:  # a snapshot of the candidates: the keys that start with a character of the text
        found = [(k, v) for c in chars for k in _BY_FIRST_CHAR.get(c, ())
                 if len(k) <= len(text) and (v := _VISUAL_TO_LOGICAL.get(k)) is not None]
    hits = sorted((kv for kv in found if kv[0] in text), key=lambda kv: len(kv[0]), reverse=True)
    if not hits:
        return text
    pieces: list[tuple[str, bool]] = [(text, False)]  # (text, already logical)
    for key, logical_text in hits:
        nxt: list[tuple[str, bool]] = []
        for part, done in pieces:
            if done or key not in part:
                nxt.append((part, done))
                continue
            chunks = part.split(key)
            for n, chunk in enumerate(chunks):
                if n:
                    nxt.append((logical_text, True))
                if chunk:
                    nxt.append((chunk, False))
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


def _shape_line(line: str, base: str, logical_input: bool) -> tuple[str, str]:
    """(shown, logical) of one line."""
    body, tail = _split_cr(line)
    if not body or not _has_rtl_letter(body):
        return line, line
    engine = _engine()
    if engine is None:
        return line, line
    if not logical_input:
        known = _lookup_result(body)  # an Arabic result by its text: never shaped twice
        if known is not None:
            return line, known + tail
    key = (body, base, logical_input)
    with _LOCK:
        cached = _CACHE.get(key)
    if cached is not None:
        return cached[0] + tail, cached[1] + tail
    # Arabic results inside the line (a name from ltr_base, a sentence of _() in an f-string) go
    # back to their logical text, so the whole line is shaped once, in one reading order.
    source = body if logical_input else _recover(body)
    if _is_shaped(source):  # presentation forms visual() did not make: cannot be put right
        return line, line
    out = _order(engine, engine.reshape(source), base)
    _remember(out, source)
    if not _is_shaped(out):
        _remember_hebrew(out, source)
    with _LOCK:
        _CACHE[key] = (out, source)
    return out + tail, source + tail


def visual(text: str, base: str = "R", logical_input: bool = False) -> str:
    """*text* in the form a Tk label needs on Linux: joined letters, visual order, per line.

    Returns a :class:`Shaped` when it changed anything, else *text* itself. *base* is the
    paragraph direction, "R" (an interface text of a right-to-left language) or "L" (a name
    inside an English sentence). A Shaped that is not composed is already shaped and returned as
    it is; a composed one (``"  " + _("x")``) is shaped again as a whole from its logical text.
    Plain text is taken for logical text. Lines without a right-to-left letter and everything
    when the engine is missing are returned as they are. ``logical_input=True`` says *text* is
    logical for sure (a catalog translation): no remembered Arabic result is looked for in it.
    """
    if isinstance(text, Shaped):
        if not text.composed:
            return text
        text, logical_input = text.logical, True
    if not text or not _has_rtl_letter(text):
        return text
    pairs = [_shape_line(line, base, logical_input) for line in text.split("\n")]
    shown = "\n".join(p[0] for p in pairs)
    if shown == text:
        return text
    return Shaped(shown, "\n".join(p[1] for p in pairs))


def logical(text: str) -> str:
    """The logical text of *text*: a Shaped gives its own; in plain text every remembered Arabic
    result, whole or inside the text, is swapped back; everything else is kept as it is."""
    if isinstance(text, Shaped):
        return text.logical
    if not text:
        return text
    out = []
    for line in text.split("\n"):
        body, tail = _split_cr(line)
        known = _lookup_result(body) if body else None
        if known is not None:
            out.append(known + tail)
        elif body and _has_rtl_letter(body):
            out.append(_recover(body) + tail)
        else:
            out.append(line)
    return "\n".join(out)


def _leaving_line(line: str) -> str:
    body, tail = _split_cr(line)
    core = body.strip()
    if not core:
        return line
    with _LOCK:
        known = _VISUAL_TO_LOGICAL.get(core)
        if known is None:
            known = _HEBREW_TO_LOGICAL.get(core)
    if known is not None:
        lead = len(body) - len(body.lstrip())
        return body[:lead] + known + body[lead + len(core):] + tail
    if _has_rtl_letter(core):
        return _recover(body) + tail
    return line


def to_logical(text: str) -> str:
    """The logical text of *text* for text that LEAVES the screen: clipboard, log file, window
    title, tray. Like :func:`logical`, and in addition a whole line (ignoring spaces around it)
    that :func:`visual` made is recognised by its text, Hebrew too, because such text has often
    lost its Shaped identity on the way (a slice, ``str()``, ``"\\n".join``, a round trip
    through a Tk widget). Never use it for a placeholder value or for display: a raw name can
    equal an earlier Hebrew result."""
    if isinstance(text, Shaped):
        return text.logical
    if not text:
        return text
    return "\n".join(_leaving_line(line) for line in text.split("\n"))


def join(sep: str, parts: Iterable[str]) -> str:
    """``sep.join(parts)`` that keeps track of Shaped parts (the plain result when none is Shaped)."""
    items = list(parts)
    if not any(isinstance(x, Shaped) for x in (sep, *items)):
        return sep.join(items)
    return Shaped(str.join(sep, items), logical(sep).join(logical(p) for p in items), True)


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
            return base_title(self, to_logical(string) if isinstance(string, str) else string)

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
                options["title"] = to_logical(options["title"])
            held = getattr(self, "options", None)
            if isinstance(held, dict) and isinstance(held.get("title"), str):
                held["title"] = to_logical(held["title"])
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
