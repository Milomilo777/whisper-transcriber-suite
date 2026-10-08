"""System fonts for the PDF writer.

reportlab's built-in fonts (Helvetica & co.) only cover Latin-1, so a
Persian, Russian or Chinese transcript used to come out as placeholder
glyphs with its text lost. This module finds TrueType fonts the OS
already ships (nothing is bundled), registers them with reportlab on
first use, and splits each line into runs so every character is drawn
with the first font in the chain that has a glyph for it.

Fonts load lazily: a Latin-only transcript loads only the first font;
a CJK fallback (a 20 MB ``.ttc``) is parsed only when a line needs it.
Fonts reportlab cannot read (CFF/PostScript outlines, broken files) are
skipped.

reportlab itself draws Arabic-script and Hebrew text unshaped and in
logical order; ``pdf_bidi`` joins the letters and reorders right-to-left
lines before they reach this module, when its optional packages are
installed. Invisible format characters (ZWNJ, ZWJ, direction marks) are
left out of the PDF: once text is shaped and reordered they have done
their job, and the fonts draw them as a visible bar.
"""
from __future__ import annotations

import logging
import os
import re
import sys
import threading
import unicodedata
from typing import Protocol, Sequence
from xml.sax.saxutils import escape as xml_escape

log = logging.getLogger(__name__)

# (regular file names, bold file names, hint). File names are matched
# case-insensitively in every font folder; the first existing one wins.
# The hint marks fonts preferred for Han characters next to kana or
# Hangul, so Japanese and Korean text get their own glyph shapes.
_CANDIDATES: tuple[tuple[tuple[str, ...], tuple[str, ...], str], ...] = (
    # Latin, Cyrillic, Greek, plus Arabic and Hebrew in most of these.
    (("arial.ttf",), ("arialbd.ttf", "arial bold.ttf"), ""),
    (("dejavusans.ttf",), ("dejavusans-bold.ttf",), ""),
    (("liberationsans-regular.ttf",), ("liberationsans-bold.ttf",), ""),
    (("notosans-regular.ttf",), ("notosans-bold.ttf",), ""),
    (("segoeui.ttf",), ("segoeuib.ttf",), ""),
    (("tahoma.ttf",), ("tahomabd.ttf", "tahoma bold.ttf"), ""),
    (("notonaskharabic-regular.ttf",), ("notonaskharabic-bold.ttf",), ""),
    (("notosansarabic-regular.ttf",), ("notosansarabic-bold.ttf",), ""),
    (("notosanshebrew-regular.ttf",), ("notosanshebrew-bold.ttf",), ""),
    (("nirmala.ttf",), ("nirmalab.ttf",), ""),
    (("leelawui.ttf",), ("leelauib.ttf",), ""),
    # CJK. Windows first, then macOS, then common Linux packages.
    (("msyh.ttc",), ("msyhbd.ttc",), ""),
    (("yugothr.ttc", "msgothic.ttc"), ("yugothb.ttc",), "kana"),
    (("malgun.ttf",), ("malgunbd.ttf",), "hangul"),
    (("simsun.ttc",), (), ""),
    (("msjh.ttc",), ("msjhbd.ttc",), ""),
    (("arial unicode.ttf", "arialuni.ttf"), (), ""),
    (("pingfang.ttc",), (), ""),
    (("hiragino sans gb.ttc",), (), ""),
    (("applesdgothicneo.ttc",), (), "hangul"),
    (("wqy-zenhei.ttc", "wqy-microhei.ttc"), (), ""),
    (("nanumgothic.ttf",), ("nanumgothicbold.ttf",), "hangul"),
    (("droidsansfallbackfull.ttf", "droidsansfallback.ttf"), (), ""),
    (("seguisym.ttf",), (), ""),
)

_MAX_DEPTH = 4


def font_dirs() -> list[str]:
    """Folders that hold the OS's fonts on this platform."""
    home = os.path.expanduser("~")
    if sys.platform == "win32":
        windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot") or r"C:\Windows"
        dirs = [os.path.join(windir, "Fonts")]
        local = os.environ.get("LOCALAPPDATA")
        if local:
            dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
        return dirs
    if sys.platform == "darwin":
        return [
            "/System/Library/Fonts",
            "/Library/Fonts",
            os.path.join(home, "Library", "Fonts"),
        ]
    return [
        "/usr/share/fonts",
        "/usr/local/share/fonts",
        os.path.join(home, ".local", "share", "fonts"),
        os.path.join(home, ".fonts"),
    ]


def _index_fonts(dirs: Sequence[str]) -> dict[str, str]:
    """Map lower-case file name -> path for every font file in *dirs*."""
    found: dict[str, str] = {}
    for root_dir in dirs:
        if not os.path.isdir(root_dir):
            continue
        base_depth = root_dir.rstrip("\\/").count(os.sep)
        for root, subdirs, files in os.walk(root_dir):
            if root.count(os.sep) - base_depth >= _MAX_DEPTH:
                subdirs[:] = []
            for name in files:
                if name.lower().endswith((".ttf", ".ttc")):
                    found.setdefault(name.lower(), os.path.join(root, name))
    return found


class _Font(Protocol):
    name: str
    bold_name: str

    def usable(self) -> bool: ...

    def covers(self, cp: int) -> bool: ...


class SystemFont:
    """One OS font file, registered with reportlab on first use."""

    def __init__(self, path: str, bold_path: str | None, hint: str = "") -> None:
        stem = re.sub(r"[^A-Za-z0-9]+", "", os.path.splitext(os.path.basename(path))[0])
        self.name = f"WTS-{stem}"
        self.bold_name = f"{self.name}-Bold" if bold_path else self.name
        self.path = path
        self.bold_path = bold_path
        self.hint = hint
        self._cmap: dict[int, int] | None = None
        self._failed = False

    def usable(self) -> bool:
        return self._load()

    def covers(self, cp: int) -> bool:
        return self._load() and cp in (self._cmap or {})

    def _load(self) -> bool:
        if self._cmap is not None:
            return True
        if self._failed:
            return False
        from reportlab.pdfbase import pdfmetrics  # type: ignore[import-not-found]
        from reportlab.pdfbase.ttfonts import TTFont  # type: ignore[import-not-found]
        from reportlab.lib.fonts import addMapping  # type: ignore[import-not-found]

        try:
            regular = TTFont(self.name, self.path, subfontIndex=0)
            pdfmetrics.registerFont(regular)
        except Exception as e:  # noqa: BLE001 — any unreadable font is skipped
            log.info("PDF: skipping font %s: %s", self.path, e)
            self._failed = True
            return False
        if self.bold_path:
            try:
                pdfmetrics.registerFont(TTFont(self.bold_name, self.bold_path, subfontIndex=0))
            except Exception as e:  # noqa: BLE001
                log.info("PDF: no bold for %s: %s", self.path, e)
                self.bold_name = self.name
        # <b> inside a paragraph looks the bold face up through this map.
        addMapping(self.name, 0, 0, self.name)
        addMapping(self.name, 1, 0, self.bold_name)
        addMapping(self.name, 0, 1, self.name)
        addMapping(self.name, 1, 1, self.bold_name)
        self._cmap = dict(regular.face.charToGlyph)
        return True


# Zero-width and direction-control characters (U+200B-200F, 202A-202E,
# 2060-2064, 2066-2069, FEFF).
_INVISIBLE = frozenset(
    [chr(c) for c in range(0x200B, 0x2010)]
    + [chr(c) for c in range(0x202A, 0x202F)]
    + [chr(c) for c in range(0x2060, 0x2065)]
    + [chr(c) for c in range(0x2066, 0x206A)]
    + [chr(0xFEFF)]
)


def _is_attached(ch: str) -> bool:
    """Characters that belong to the run of the letter before them."""
    return ch.isspace() or unicodedata.category(ch) in ("Mn", "Mc", "Me", "Cf")


def _is_kana(cp: int) -> bool:
    return 0x3040 <= cp <= 0x30FF or 0x31F0 <= cp <= 0x31FF or 0xFF66 <= cp <= 0xFF9F


def _is_hangul(cp: int) -> bool:
    return 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF or 0x3130 <= cp <= 0x318F


def _is_cjk(cp: int) -> bool:
    return (
        0x2E80 <= cp <= 0x9FFF  # radicals, CJK punctuation, kana, Han
        or 0xAC00 <= cp <= 0xD7AF
        or 0xF900 <= cp <= 0xFAFF
        or 0xFF00 <= cp <= 0xFFEF  # full-width forms
        or 0x20000 <= cp <= 0x3FFFF
    )


class FontChain:
    """Ordered fonts; each character goes to the first font with its glyph."""

    def __init__(self, fonts: Sequence[_Font], prefer: dict[str, str] | None = None) -> None:
        self.fonts = list(fonts)
        self.prefer = dict(prefer or {})
        self._base: _Font | None = None
        self._base_known = False

    @property
    def base(self) -> _Font | None:
        """The first usable font: the paragraph font, and the fallback
        for characters no font covers."""
        if not self._base_known:
            self._base = next((f for f in self.fonts if f.usable()), None)
            self._base_known = True
        return self._base

    def font_for(self, ch: str, preferred: _Font | None = None) -> _Font | None:
        cp = ord(ch)
        if preferred is not None and _is_cjk(cp) and preferred.covers(cp):
            return preferred
        return next((f for f in self.fonts if f.covers(cp)), None)

    def _preferred(self, text: str) -> _Font | None:
        hint = ""
        for ch in text:
            cp = ord(ch)
            if _is_kana(cp):
                hint = "kana"
                break
            if _is_hangul(cp):
                hint = "hangul"
                break
        name = self.prefer.get(hint) if hint else None
        return next((f for f in self.fonts if f.name == name), None) if name else None

    def split_runs(self, text: str) -> list[tuple[str, str]]:
        """``[(font name, chunk), ...]`` covering *text* in order."""
        base = self.base
        if base is None:
            return [("", text)] if text else []
        preferred = self._preferred(text)
        runs: list[list[str]] = []
        pending = ""
        for ch in text:
            if ch in _INVISIBLE:
                continue
            if _is_attached(ch):
                if runs:
                    runs[-1][1] += ch
                else:
                    pending += ch
                continue
            font = self.font_for(ch, preferred) or base
            if runs and runs[-1][0] == font.name:
                runs[-1][1] += ch
            else:
                runs.append([font.name, pending + ch])
                pending = ""
        if pending:
            runs.append([base.name, pending])
        return [(name, chunk) for name, chunk in runs]

    def markup(self, text: str, bold: bool = False) -> str:
        """reportlab paragraph markup for *text*: escaped, with a
        ``<font>`` tag around every run not in the base font.

        reportlab ignores an enclosing ``<b>`` once a ``<font name>``
        sets the face, so with *bold* the fallback runs name their bold
        face directly; the caller still wraps the result in ``<b>`` for
        the base-font runs.
        """
        base = self.base
        by_name = {f.name: f for f in self.fonts}
        out: list[str] = []
        for name, chunk in self.split_runs(text):
            if base is None or name == base.name:
                out.append(xml_escape(chunk))
            else:
                face = by_name[name].bold_name if bold else name
                out.append(f'<font name="{face}">{xml_escape(chunk)}</font>')
        return "".join(out)


def build_chain(dirs: Sequence[str]) -> FontChain:
    index = _index_fonts(dirs)
    fonts: list[SystemFont] = []
    prefer: dict[str, str] = {}
    for regulars, bolds, hint in _CANDIDATES:
        path = next((index[n] for n in regulars if n in index), None)
        if path is None:
            continue
        bold = next((index[n] for n in bolds if n in index), None)
        font = SystemFont(path, bold, hint)
        fonts.append(font)
        if hint and hint not in prefer:
            prefer[hint] = font.name
    return FontChain(fonts, prefer)


_DEFAULT_CHAIN: FontChain | None = None
_LOCK = threading.Lock()


def default_chain() -> FontChain:
    """The chain for this machine's font folders, built once."""
    global _DEFAULT_CHAIN
    with _LOCK:
        if _DEFAULT_CHAIN is None:
            _DEFAULT_CHAIN = build_chain(font_dirs())
            if _DEFAULT_CHAIN.base is None:
                log.warning(
                    "PDF: no TrueType system font found; using Helvetica, "
                    "which shows only Latin text"
                )
        return _DEFAULT_CHAIN
