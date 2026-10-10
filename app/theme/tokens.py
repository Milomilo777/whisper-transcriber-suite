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

# Text of a pressed primary ("Accent.TButton") button, both themes. sv_ttk's own pressed text
# (#25536a on the dark theme's #4ba6d5, #c1d8ee on the light theme's #327ec5) reads 3.06:1 and
# 2.91:1; black reads 7.7:1 and 4.9:1. The other states already pass 4.5:1 (see
# tests/app/test_accent_button_contrast.py, which measures them from sv_ttk's own images).
ACCENT_BUTTON_PRESSED_TEXT = "#000000"

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
# Book showcase panel: the white mat the cover picture sits on (the official covers are shot on
# white) with its hairline edge, and the neutral book drawn while a cover is not available.
BOOK_COVER_MAT = "#ffffff"
BOOK_COVER_EDGE = "#d5dbe1"
BOOK_PLACEHOLDER = "#cbd5e1"
# Rounded program chips (app/widgets/chip_cloud.py): one palette per theme, drawn on a Canvas,
# so they are read at draw time instead of being swapped by theme_colours. A chip has a tinted
# fill and a 1 px border that reaches 3:1 against the panel (it must be seen without relying on
# the text); the selected chip is solid. "toggle_fg" is the text of the ghost "All programs"
# control, drawn straight on the panel.
CHIP_PALETTES = {
    "light": {
        "normal_bg": "#eaf2fb", "normal_border": "#5b8bc0", "normal_fg": "#0b4f8c",
        "hover_bg": "#d6e6f7", "hover_border": "#0b5cad", "hover_fg": "#0b4f8c",
        "selected_bg": "#0b5cad", "selected_fg": "#ffffff",
        "toggle_fg": "#0b5cad", "ring": "#0b5cad",
    },
    "dark": {
        "normal_bg": "#1e2a38", "normal_border": "#4f7fb0", "normal_fg": "#9ccbff",
        "hover_bg": "#26384d", "hover_border": "#7fb2e8", "hover_fg": "#cfe6ff",
        "selected_bg": "#57c8ff", "selected_fg": "#0b1a26",
        "toggle_fg": "#7fb2e8", "ring": "#7fb2e8",
    },
}
# Program buttons on the hero banner (same pill shape as the chips). The banner is dark in both
# themes, so one style serves both: a translucent white pill over a faint dark scrim (the scrim
# keeps white text at 4.5:1 even where the banner turns teal), a white border, and a gold border
# on hover. Alphas are 0..1; layers are painted scrim, then fill, over the banner gradient.
HERO_PILLS = {
    "scrim": "#000000", "scrim_alpha": 0.22,
    "fill": "#ffffff", "rest_alpha": 0.12, "hover_alpha": 0.22,
    "border": "#ffffff", "border_alpha": 0.55, "hover_border": HERO_ACCENT,
    "text": "#ffffff", "ring": HERO_ACCENT,
}

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
