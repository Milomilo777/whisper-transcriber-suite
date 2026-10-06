"""Fonts per writing system for the widgets that show file names and transcript lines.

Tk draws a line with one base font and borrows only the glyphs that font lacks from another
installed font. On Windows this goes wrong for several scripts the app transcribes:

- the line keeps the base font's height, so tall vowel signs and stacked marks of the Indic
  scripts, Sinhala, Thai, Khmer and Myanmar are cut off (Courier New in a ``tk.Text``; Myanmar
  even in a Treeview row);
- a Sinhala conjunct joined by U+200D ZERO WIDTH JOINER falls apart: the base font has the
  joiner, so Tk splits the borrowed run around it;
- Chinese and Japanese text gets whichever CJK font Tk finds first, so the glyph shapes follow
  the wrong region (a Traditional Chinese font for Japanese, for example).

Naming the right font for the row or line fixes all three. Measured with every language of the
caption-language list on Windows 10; right-to-left order is a separate problem no font fixes.

Windows only: macOS and Linux keep the platform's fonts and font fallback. A font that is not
installed is skipped (logged once) and the widget keeps the font it had.
"""
from __future__ import annotations

import bisect
import logging
import sys
import tkinter as tk
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


def _row_need(widget: tk.Misc, family: str, size: int) -> int:
    return int(tkfont.Font(root=widget, family=family, size=size).metrics("linespace")) + _ROW_PAD


def apply_theme_fonts(root: tk.Misc) -> None:
    """Call after every ``sv_ttk.set_theme``: the Treeview font fix plus the taller row styles.

    Setting a ttk style option makes Tk send <<ThemeChanged>> to every widget, and sv_ttk then
    resets each ttk.Entry / Combobox to its own font. So the row styles a script font may need
    ("WtsRows28.Treeview") are set up here, together with the theme, and a tree only switches
    to one later (``tree_row_tags``), which changes no style.
    """
    fix_tree_font(root)
    if not _on_windows():
        return
    style = ttk.Style(root)
    base = _int(style.lookup("Treeview", "rowheight"))
    size = _tree_font_size(root)
    installed = installed_families(root)
    for key, family in tokens.FONT_FAMILIES_WINDOWS.items():
        if key != "ui" and family in installed:
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

    ttk applies a tag's font to the whole row. The first row in a font configures the tag and,
    if that font's lines are taller than the rows, gives this tree a row height that fits them.
    """
    key = font_key(" ".join(texts), language) if _on_windows() else None
    family = None if key is None else _installed_family(key, installed_families(tree))
    if family is None:
        return ()
    tag = _TREE_TAG + family.replace(" ", "_")
    if not str(tree.tag_configure(tag, "font")):
        size = _tree_font_size(tree, str(tree.cget("style")))
        tree.tag_configure(tag, font=(family, size))
        _fit_rows(tree, _row_need(tree, family, size))
    return (tag,)


# ------------------------------------------------------------------------- tk.Text

def use_text_font(widget: tk.Text) -> bool:
    """A proportional font with room for tall marks instead of Tk's Courier New (Windows only)."""
    if not _on_windows():
        return False
    family = _installed_family("ui", installed_families(widget))
    if family is None:
        return False
    widget.configure(font=(family, tokens.FONT_BODY))
    return True


def tag_script_lines(widget: tk.Text, start: str = "1.0", end: str = "end",
                     language: str | None = None) -> None:
    """Give each line from ``start`` to ``end`` the font its script needs (Windows only)."""
    if not _on_windows():
        return
    first = int(widget.index(start).split(".")[0])
    last = int(widget.index(end).split(".")[0])
    names = set(widget.tag_names())
    for tag in names:
        if tag.startswith(_TEXT_TAG):
            widget.tag_remove(tag, f"{first}.0", f"{last}.end")
    for n in range(first, last + 1):
        key = font_key(widget.get(f"{n}.0", f"{n}.end"), language)
        family = None if key is None else _installed_family(key, installed_families(widget))
        if family is None:
            continue
        tag = _TEXT_TAG + family.replace(" ", "_")
        if tag not in names:
            widget.tag_configure(tag, font=(family, tokens.FONT_BODY))
            names.add(tag)
        widget.tag_add(tag, f"{n}.0", f"{n}.end")
