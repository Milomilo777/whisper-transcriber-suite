"""Design tokens: every colour, spacing step and type size the UI uses lives here.

Widgets import a name from this module instead of writing a literal ``"#rrggbb"``, so a colour is
changed in one place.  Colours that must follow the Light/Dark switch come as a ``(light, dark)``
pair in ``LIGHT`` / ``DARK`` (read with ``palette(theme)``); the rest read the same on both themes
and are plain module constants.
"""
from __future__ import annotations

# --------------------------------------------------------------- text and links
LINK = "#1a73e8"           # clickable text
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
