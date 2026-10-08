"""Design tokens: every colour, spacing step and type size the UI uses lives here.

Widgets import a name from this module instead of writing a literal ``"#rrggbb"``, so a colour is
changed in one place.  The module constants are the light-theme colours. Text, status and row
colours that sv_ttk's dark panels would make unreadable have a dark variant in ``DARK_VARIANTS``:
widgets read them through ``themed(tokens.X)``, and ``app.theme.theme_colours`` swaps the colours
of existing widgets when the theme changes. The console colours come as a ``(light, dark)`` pair
in ``LIGHT`` / ``DARK`` (read with ``palette(theme)``).
"""
from __future__ import annotations

# --------------------------------------------------------------- text and links
LINK = "#1a66d9"           # clickable text (5.1:1 on the light panel)
TEXT_DISABLED = "#a0a0a0"  # faint / unavailable text
TEXT_MUTED = "#64748b"     # secondary captions
TEXT_SUBTLE = "#94a3b8"    # separators and tertiary hints

# ------------------------------------------------------------- status colours
SUCCESS_TEXT = "#3a8f3a"
WARNING_TEXT = "#b06a00"
DANGER_TEXT = "#b00020"
DANGER_ICON = "#c62828"

# Darker variants for text drawn on tinted rows or light panels (higher contrast).
SUCCESS_STRONG = "#1e6f1e"
WARNING_STRONG = "#9c6f00"
DANGER_STRONG = "#a00000"
TEXT_MISSING = "#8a8a8a"   # names of models that are not downloaded yet

# Hardware chips: where the model runs.
CHIP_GPU = "#2e9e44"
CHIP_CPU = "#d08a1d"

# --------------------------------------------------------------- tree row tints
ROW_ACTIVE = "#fffacd"   # karaoke highlight
ROW_SUSPECT = "#ffe0e0"
ROW_WARN = "#ffe6b3"

# ------------------------------------------------------------------- tooltips
TOOLTIP_BG = "#ffffe0"
TOOLTIP_FG = "#000000"

# --------------------------------------------------------------- SMTV tab hero
HERO_TEXT = "#f8fafc"
HERO_SUB = "#bae6fd"
HERO_ACCENT = "#fde68a"   # warm gold
THUMB_BG = "#1e293b"
PROGRAM_ACCENT = "#0891b2"

# ------------------------------------------------------- theme-dependent colours
LIGHT = {
    "console_bg": "#f5f5f5",
    "console_fg": "#1a6b1a",
    "console_error_fg": DANGER_ICON,
}
DARK = {
    "console_bg": "#0d0d0d",
    "console_fg": "#8be08b",
    "console_error_fg": "#ff6b6b",
}


def palette(theme: str) -> dict[str, str]:
    """The colour table for a resolved theme name (``"light"`` or anything else = dark)."""
    return LIGHT if theme == "light" else DARK


# ------------------------------------------------------ dark-theme variants
# Light-theme colour -> the colour that replaces it on the dark theme. Text keeps at least
# 4.5:1 (WCAG AA) on sv_ttk's dark panel (#1c1c1c) and on its raised fields (#2b2b2b); the row
# tints are dark so the theme's light text (#fafafa) and the strong status colours stay readable
# on them. No variant may equal a light colour, so a swap can always be undone.
DARK_PANELS = ("#1c1c1c", "#2b2b2b")
LIGHT_PANEL = "#fafafa"
DARK_VARIANTS = {
    LINK: "#6cb4ff",
    TEXT_MUTED: "#a3adbb",
    SUCCESS_TEXT: "#66bb6a",
    WARNING_TEXT: "#ffb74d",
    DANGER_TEXT: "#ff8a80",
    DANGER_ICON: "#ff6b6b",
    SUCCESS_STRONG: "#a5d6a7",
    WARNING_STRONG: "#ffcc80",
    DANGER_STRONG: "#f4a6a6",
    TEXT_MISSING: "#a6a6a6",
    CHIP_GPU: "#4caf50",
    ROW_ACTIVE: "#4a4520",
    ROW_SUSPECT: "#5a2a2a",
    ROW_WARN: "#523d16",
}
ROW_TINTS = (ROW_ACTIVE, ROW_SUSPECT, ROW_WARN)
LIGHT_VARIANTS = {dark: light for light, dark in DARK_VARIANTS.items()}

_theme = "light"


def set_theme(theme: str) -> None:
    """Record the resolved theme (``"light"`` or ``"dark"``) that ``themed`` answers for."""
    global _theme
    _theme = "light" if theme == "light" else "dark"


def current_theme() -> str:
    return _theme


def themed(colour: str, theme: str | None = None) -> str:
    """``colour`` (a light-theme token) as the current (or the given) theme shows it."""
    if (theme or _theme) == "light":
        return LIGHT_VARIANTS.get(colour, colour)
    return DARK_VARIANTS.get(colour, colour)


# -------------------------------------------------------------- spacing scale
SPACE_XS = 4
SPACE_SM = 8
SPACE_MD = 12
SPACE_LG = 16
SPACE_XL = 24
SPACE_XXL = 32
SPACING = (SPACE_XS, SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XL, SPACE_XXL)

# ------------------------------------------------------------------ type scale
# Point sizes.  The family is left to sv_ttk / the platform default font.
FONT_CAPTION = 9
FONT_BODY = 10
FONT_SUBTITLE = 12
FONT_TITLE = 14
FONT_HEADLINE = 18
TYPE_SCALE = (FONT_CAPTION, FONT_BODY, FONT_SUBTITLE, FONT_TITLE, FONT_HEADLINE)
# Pixels added above and below each line of a transcript text box (tk.Text spacing1 /
# spacing3): Segoe UI's line leaves no room for Lao marks below the line.
TEXT_LINE_GAP = 1

# ------------------------------------------------------------- font families
# Windows only (see app.theme.script_fonts): elsewhere the platform fonts stay.
# "ui": the proportional font of the transcript text boxes and, on Windows 10, of the
# Treeview rows (sv_ttk asks for the Windows 11 font "Segoe UI Variable Text"; Tk then
# uses Arial). The other keys (from ``script_fonts.font_key``) name the font for file
# names and transcript lines that the UI font draws badly: a Sinhala conjunct split,
# Myanmar marks cut off by the line height, Chinese glyph shapes for Japanese. Indic
# scripts, Thai, Lao and Khmer have no entry on purpose: Segoe UI's line fits them.
FONT_FAMILIES_WINDOWS = {
    "ui": "Segoe UI",
    "sinhala": "Nirmala UI",
    "myanmar": "Myanmar Text",
    "zh-hans": "Microsoft YaHei UI",
    "zh-hant": "Microsoft JhengHei UI",
    "ja": "Yu Gothic UI",
}
