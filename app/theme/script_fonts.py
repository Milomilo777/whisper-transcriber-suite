"""Fonts per writing system for the widgets that show file names and transcript lines.

Tk draws a line with one base font and borrows only the glyphs that font lacks from another
installed font. On Windows this goes wrong for several scripts the app transcribes:

- the line keeps the base font's height, so tall vowel signs and stacked marks are cut off:
  Indic scripts, Sinhala, Thai and Khmer under Courier New in a ``tk.Text``, Myanmar even under
  Segoe UI and in a Treeview row;
- a Sinhala conjunct joined by U+200D ZERO WIDTH JOINER falls apart: the base font has the
  joiner, so Tk splits the borrowed run around it;
- Chinese and Japanese text gets whichever CJK font Tk finds first, so the glyph shapes follow
  the wrong region (a Traditional Chinese font for Japanese, for example).

Segoe UI as the base font fixes the line height for Indic scripts, Thai, Lao and Khmer. Sinhala,
Myanmar and Han get a font of their own per row or line. Measured with every language of the
caption-language list on Windows 10; right-to-left order is a separate problem no font fixes.

A font of their own has a cost: Tk then draws the whole line as one run, and Tk on Windows draws a
run in pieces of about 200 bytes, cut wherever that falls (``MultiFontTextOut`` in
win/tkWinFont.c), even inside a cluster. Text boxes therefore cut such lines into pieces under that
size, after a space or between clusters, each piece in its own tag (a tag boundary starts a new
run). Treeview rows cannot be cut, so a Sinhala or Myanmar row longer than that keeps the default
font: its words are then separate runs (Segoe UI draws the spaces and separators), and a mark that
the line height clips is the lesser harm than a cluster split in two. That cost is why scripts
that Segoe UI's line already fits get no font of their own.

A Treeview tag's font restyles every column of the row. Han text never lost pixels under the
default fallback, so trees with more than one column give it no font (the progress bars and the
times of all rows stay alike); single-column trees and text boxes keep it. For the same reason a
script font in a multi-column tree keeps the tree's size and row height (the list keeps its row
count; Myanmar's tallest marks may lose a pixel). In a single-column tree a row font whose line is
taller than the rows is used a little smaller (down to ``_ROW_MIN_SCALE``) before the tree gets
taller rows.

Windows only: macOS and Linux keep the platform's fonts and font fallback. A font that is not
installed is skipped (logged once) and the widget keeps the font it had.
"""
from __future__ import annotations

import bisect
import logging
import sys
import tkinter as tk
import unicodedata
from collections import Counter
from collections.abc import Collection
from tkinter import font as tkfont
from tkinter import ttk

from app.theme import tokens

logger = logging.getLogger(__name__)

# (first code point, last code point, script), sorted by the first code point.
_RANGES: tuple[tuple[int, int, str], ...] = (
    (0x0900, 0x0D7F, "indic"),     # Devanagari .. Malayalam
    (0x0D80, 0x0DFF, "sinhala"),
    (0x0E00, 0x0E7F, "thai"),
    (0x0E80, 0x0EFF, "lao"),
    (0x1000, 0x109F, "myanmar"),
    (0x1780, 0x17FF, "khmer"),
    (0x19E0, 0x19FF, "khmer"),     # Khmer symbols
    (0x1CD0, 0x1CFF, "indic"),     # Vedic extensions
    (0x3040, 0x30FF, "kana"),      # Hiragana, Katakana
    (0x31F0, 0x31FF, "kana"),      # Katakana phonetic extensions
    (0x3400, 0x4DBF, "han"),       # CJK extension A
    (0x4E00, 0x9FFF, "han"),       # CJK unified ideographs
    (0xA8E0, 0xA8FF, "indic"),     # Devanagari extended
    (0xA9E0, 0xA9FF, "myanmar"),   # Myanmar extended-B
    (0xAA60, 0xAA7F, "myanmar"),   # Myanmar extended-A
    (0xF900, 0xFAFF, "han"),       # CJK compatibility ideographs
    (0xFF66, 0xFF9F, "kana"),      # half-width Katakana
    (0x20000, 0x323AF, "han"),     # CJK extensions B-H
)
_STARTS = [first for first, _last, _script in _RANGES]
# Tie-break when two scripts have as many characters: the one with the tallest marks first.
_TIE_ORDER = ("myanmar", "sinhala", "indic", "khmer", "thai", "lao", "kana", "han")

TREE_FONT = "WtsTreeFont"     # named font of the Treeview rows on Windows 10
_TREE_TAG = "script-font-"   # Treeview tags: "script-font-Myanmar_Text"
_TEXT_TAG = "script-font-"   # tk.Text tags, same shape
_ROW_PAD = 3                 # sv_ttk's row height = line height + 3
_ROW_STYLE = "WtsRows{}.Treeview"  # a Treeview style with taller rows, by height in pixels
_ROW_MIN_SCALE = 0.8         # a row font may shrink to 80 % of the tree's size to fit the rows
_HAN_KEYS = frozenset({"ja", "zh-hans", "zh-hant"})
RUN_BYTES = 150              # pieces of a tagged Text line stay under Tk's ~200-byte drawing runs

_families: frozenset[str] | None = None
_missing_logged: set[str] = set()


def _on_windows() -> bool:
    return sys.platform.startswith("win")


# ------------------------------------------------------------------ choosing a font

def script_of(ch: str) -> str | None:
    """The script key of one character, or None for scripts the UI font draws well."""
    cp = ord(ch)
    i = bisect.bisect_right(_STARTS, cp) - 1
    if i >= 0 and cp <= _RANGES[i][1]:
        return _RANGES[i][2]
    return None


def text_script(text: str) -> str | None:
    """The script most of the text's characters belong to, among the scripts in ``_RANGES``.

    Latin, Cyrillic, Arabic and the other scripts the UI font already draws well are not counted,
    so ``interview_<Myanmar name>.mp4`` is Myanmar. Japanese mixes kana and kanji: any kana makes
    the Han characters count as kana too. None when no character belongs to those scripts.
    """
    counts = Counter(s for s in map(script_of, text) if s is not None)
    if not counts:
        return None
    if counts["kana"]:
        counts["kana"] += counts.pop("han", 0)
    return max(counts, key=lambda s: (counts[s], -_TIE_ORDER.index(s)))


def han_region(language: str | None) -> str | None:
    """"ja", "zh-hant" or "zh-hans" for a language code ("zh-Hant,zh-TW" style lists too)."""
    code = (language or "").split(",")[0].strip().lower().replace("_", "-")
    if code == "ja" or code.startswith("ja-"):
        return "ja"
    if code in ("yue", "zh-tw", "zh-hk", "zh-mo") or code.startswith("zh-hant"):
        return "zh-hant"
    if code == "zh" or code.startswith("zh-"):
        return "zh-hans"
    return None


def font_key(text: str, language: str | None = None) -> str | None:
    """Key into ``tokens.FONT_FAMILIES_WINDOWS`` for the text, or None to keep the widget's font.

    Han characters without kana get the regional font of ``language`` (the transcript or caption
    language); with an unknown language they keep the default fallback rather than a guess.
    """
    script = text_script(text)
    if script == "kana":
        return "ja"
    if script == "han":
        return han_region(language)
    return script


def _installed_family(key: str, installed: Collection[str]) -> str | None:
    family = tokens.FONT_FAMILIES_WINDOWS.get(key)
    if family is None:
        return None
    if family in installed:
        return family
    if family not in _missing_logged:
        _missing_logged.add(family)
        logger.info("Font %r is not installed; %s text keeps the default font", family, key)
    return None


def family_for(text: str, language: str | None = None, *, installed: Collection[str]) -> str | None:
    """The installed font family for this text on Windows, or None to keep the widget's font."""
    if not _on_windows():
        return None
    key = font_key(text, language)
    return None if key is None else _installed_family(key, installed)


def installed_families(widget: tk.Misc) -> frozenset[str]:
    """Every font family Tk can use (read once per process)."""
    global _families
    if _families is None:
        _families = frozenset(str(f) for f in tkfont.families(widget))
    return _families


# ------------------------------------------------------------------------ Treeview

def _int(value: object) -> int:
    try:
        return int(str(value))
    except ValueError:
        return 0


def fix_tree_font(root: tk.Misc) -> bool:
    """Windows 10: Treeview rows in Segoe UI where sv_ttk's Windows 11 font is missing.

    sv_ttk asks for "Segoe UI Variable Text", which Windows 10 does not have, so Tk falls back to
    Arial, and Arial makes Tk borrow CJK glyphs from a different font per character. Style
    settings belong to the theme, so ``apply_theme_fonts`` runs this after every theme switch.
    True when the rows use the fixed font.
    """
    if not _on_windows():
        return False
    style = ttk.Style(root)
    current = str(style.lookup("Treeview", "font"))
    if current == TREE_FONT:
        return True
    try:
        base = tkfont.nametofont(current, root=root) if current else None
    except tk.TclError:
        base = None
    if base is None or base.actual("family") == base.cget("family"):
        return False  # no theme font, or the asked-for font is installed (Windows 11)
    family = _installed_family("ui", installed_families(root))
    if family is None:
        return False
    if TREE_FONT in root.tk.splitlist(root.tk.call("font", "names")):
        root.tk.call("font", "configure", TREE_FONT, "-family", family, "-size", base.cget("size"))
    else:
        root.tk.call("font", "create", TREE_FONT, "-family", family, "-size", base.cget("size"))
    line = _int(root.tk.call("font", "metrics", TREE_FONT, "-linespace"))
    rows = max(_int(style.lookup("Treeview", "rowheight")), line + _ROW_PAD)
    style.configure("Treeview", font=TREE_FONT, rowheight=rows)
    return True


def _tree_font_size(widget: tk.Misc, style_name: str = "Treeview") -> int:
    name = str(ttk.Style(widget).lookup(style_name or "Treeview", "font"))
    try:
        return int(tkfont.nametofont(name, root=widget).cget("size")) if name else tokens.FONT_BODY
    except tk.TclError:
        return tokens.FONT_BODY


def _linespace(widget: tk.Misc, family: str, size: int) -> int:
    return int(tkfont.Font(root=widget, family=family, size=size).metrics("linespace"))


def _row_need(widget: tk.Misc, family: str, size: int) -> int:
    return _linespace(widget, family, size) + _ROW_PAD


def _fitting_size(widget: tk.Misc, family: str, size: int, rowheight: int) -> int | None:
    """The largest size from ``size`` down to ``_ROW_MIN_SCALE`` of it whose line fits the rows.

    Measured on Windows 10 at 100 %: Myanmar Text 10 (23-pixel line) in sv_ttk's 22-pixel rows
    lost the top pixel of the tallest marks; at 9 (21 pixels) no sample lost a pixel. Negative
    sizes are pixels, positive ones points. None when no size fits (the tree then grows).
    """
    if rowheight <= 0:
        return None
    step = 1 if size > 0 else -1
    s = size
    while s != 0 and abs(s) >= abs(size) * _ROW_MIN_SCALE:
        if _linespace(widget, family, s) <= rowheight:
            return s
        s -= step
    return None


def apply_theme_fonts(root: tk.Misc) -> None:
    """Call after every ``sv_ttk.set_theme``: the Treeview font fix plus the taller row styles.

    Setting a ttk style option makes Tk send <<ThemeChanged>> to every widget, and sv_ttk then
    resets each ttk.Entry / Combobox to its own font. So the row styles a script font may need
    ("WtsRows28.Treeview": only a font that does not fit the rows even a little smaller) are set
    up here, together with the theme, and a tree only switches to one later
    (``tree_row_tags``), which changes no style.
    """
    fix_tree_font(root)
    if not _on_windows():
        return
    style = ttk.Style(root)
    base = _int(style.lookup("Treeview", "rowheight"))
    size = _tree_font_size(root)
    installed = installed_families(root)
    for key, family in tokens.FONT_FAMILIES_WINDOWS.items():
        if key != "ui" and family in installed and _fitting_size(root, family, size, base) is None:
            need = _row_need(root, family, size)
            if need > base:
                style.configure(_ROW_STYLE.format(need), rowheight=need)


def _fit_rows(tree: ttk.Treeview, need: int) -> None:
    """Rows at least ``need`` pixels high in this tree only (other trees keep theirs)."""
    current = str(tree.cget("style"))
    if current and not current.startswith(_ROW_STYLE.split("{")[0]):
        return  # a tree with its own style is left alone
    style = ttk.Style(tree)
    if need <= _int(style.lookup(current or "Treeview", "rowheight")):
        return
    name = _ROW_STYLE.format(need)
    if "rowheight" not in (style.configure(name) or {}):
        style.configure(name, rowheight=need)  # not prepared by apply_theme_fonts
    tree.configure(style=name)


def tree_row_tags(tree: ttk.Treeview, *texts: str, language: str | None = None) -> tuple[str, ...]:
    """The tag that gives a row the font its text's script needs, or ``()``.

    ``texts`` are the row's cells in that script (a file name, a transcript line). ttk applies a
    tag's font to the whole row, which leads to three rules (module docstring): a Sinhala or
    Myanmar cell longer than ``RUN_BYTES`` keeps the default font, because one font would make Tk
    cut the row inside a cluster; a tree with more than one column gives Han no font and other
    scripts their font at the tree's size and row height, so the other columns look like every
    other row's; in a single-column tree the first row in a font configures the tag, a little
    smaller if that makes its line fit the rows, else this tree gets taller rows.
    """
    key = font_key(" ".join(texts), language) if _on_windows() else None
    if key is None:
        return ()
    columns = len(tree.tk.splitlist(tree.cget("columns")))
    if key in _HAN_KEYS and columns > 1:
        return ()
    if key not in _HAN_KEYS and any(text_script(t) == key and sum(map(_tk_bytes, t)) > RUN_BYTES
                                    for t in texts):
        return ()
    family = _installed_family(key, installed_families(tree))
    if family is None:
        return ()
    tag = _TREE_TAG + family.replace(" ", "_")
    if not str(tree.tag_configure(tag, "font")):
        style_name = str(tree.cget("style")) or "Treeview"
        size = _tree_font_size(tree, style_name)
        if columns > 1:
            # The other columns (status, a progress bar of block characters, times) take this
            # font too: at the tree's own size and row height they look like every other row's,
            # and the list keeps its row count; a line taller than the rows loses at most its
            # outermost pixel rows (Myanmar Text 10 in 22-pixel rows: 2 pixels in 2 of 7 samples).
            tree.tag_configure(tag, font=(family, size))
            return (tag,)
        rows = _int(ttk.Style(tree).lookup(style_name, "rowheight"))
        fitted = _fitting_size(tree, family, size, rows)
        tree.tag_configure(tag, font=(family, size if fitted is None else fitted))
        if fitted is None:
            _fit_rows(tree, _row_need(tree, family, size))
    return (tag,)


# ------------------------------------------------------------------------- tk.Text

def use_text_font(widget: tk.Text) -> bool:
    """A proportional font with room for tall marks instead of Tk's Courier New (Windows only).

    Segoe UI's line is one pixel shallower below the baseline than Courier New's, so each line
    also gets ``tokens.TEXT_LINE_GAP`` pixels above and below (marks below Lao letters). The
    taller lines would make the box ask for more room and push the widgets below it out of a
    small window, so its ``height`` (in lines) drops until the box asks for no more pixels than
    before.
    """
    if not _on_windows():
        return False
    family = _installed_family("ui", installed_families(widget))
    if family is None:
        return False
    before = widget.winfo_reqheight()
    lines = _int(widget.cget("height"))
    widget.configure(font=(family, tokens.FONT_BODY),
                     spacing1=tokens.TEXT_LINE_GAP, spacing3=tokens.TEXT_LINE_GAP)
    while lines > 1 and widget.winfo_reqheight() > before:
        lines -= 1
        widget.configure(height=lines)
    return True


def _tk_bytes(ch: str) -> int:
    """Bytes Tk 8.6 stores for a character (a character outside the BMP is two 3-byte halves)."""
    cp = ord(ch)
    return 1 if cp < 0x80 else 2 if cp < 0x800 else 3 if cp < 0x10000 else 6


# A piece may end before ``i`` unless text[i] continues a cluster (a mark or a joiner) or text[i-1]
# joins its neighbours: a virama by name (Indic, Myanmar), the Sinhala al-lakuna and Khmer coeng
# (viramas by another name), a joiner, or a Thai / Lao vowel written before its consonant.
_JOINS_NEXT = {0x200C, 0x200D, 0x0DCA, 0x17D2} | set(range(0x0E40, 0x0E45)) | set(range(0x0EC0, 0x0EC5))


def _cluster_boundary(text: str, i: int) -> bool:
    nxt, prev = text[i], text[i - 1]
    if unicodedata.category(nxt).startswith("M") or ord(nxt) in (0x200C, 0x200D):
        return False
    return ord(prev) not in _JOINS_NEXT and "VIRAMA" not in unicodedata.name(prev, "")


def run_pieces(line: str, limit: int = RUN_BYTES) -> list[tuple[int, int]]:
    """Cut a line into pieces of at most ``limit`` Tk bytes: after a space where possible, else
    between clusters (a single cluster longer than the limit is the only forced cut)."""
    pieces: list[tuple[int, int]] = []
    start = 0
    while start < len(line):
        size, end = 0, start
        while end < len(line) and size + _tk_bytes(line[end]) <= limit:
            size += _tk_bytes(line[end])
            end += 1
        if end >= len(line):
            pieces.append((start, len(line)))
            break
        cut = next((j for j in range(end, start, -1) if line[j - 1].isspace()), None)
        if cut is None:
            cut = next((j for j in range(end, start, -1) if _cluster_boundary(line, j)), end)
        pieces.append((start, cut))
        start = cut
    return pieces


def _tk_index(line: str, offset: int) -> int:
    """Tk 8.6 counts a character outside the BMP as two (UTF-16 surrogates)."""
    return offset + sum(1 for ch in line[:offset] if ord(ch) > 0xFFFF)


def tag_script_lines(widget: tk.Text, start: str = "1.0", end: str = "end",
                     language: str | None = None) -> None:
    """Give each line from ``start`` to ``end`` the font its script needs (Windows only).

    The line is tagged in pieces (``run_pieces``), alternating two tags with the same font, so Tk
    never draws more than one piece in one run.
    """
    if not _on_windows():
        return
    first = int(widget.index(start).split(".")[0])
    last = int(widget.index(end).split(".")[0])
    names = set(widget.tag_names())
    for tag in names:
        if tag.startswith(_TEXT_TAG):
            widget.tag_remove(tag, f"{first}.0", f"{last}.end")
    for n in range(first, last + 1):
        line = widget.get(f"{n}.0", f"{n}.end")
        key = font_key(line, language)
        family = None if key is None else _installed_family(key, installed_families(widget))
        if family is None:
            continue
        base = _TEXT_TAG + family.replace(" ", "_")
        for k, (a, b) in enumerate(run_pieces(line)):
            tag = base if k % 2 == 0 else base + "-b"
            if tag not in names:
                widget.tag_configure(tag, font=(family, tokens.FONT_BODY))
                names.add(tag)
            widget.tag_add(tag, f"{n}.{_tk_index(line, a)}", f"{n}.{_tk_index(line, b)}")
