"""The primary ("Accent.TButton") button's text keeps 4.5:1 (WCAG AA) on its fill, in both themes.

The fill of each state is a picture in sv_ttk's sprite sheet, so the background is sampled from
the real image (its middle pixel, which is flat) and the text colour is what Tk answers for that
state after the app's own style fix. The disabled state is exempt (WCAG: inactive components).
"""
from __future__ import annotations

import os
import re

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import ttk  # noqa: E402

import sv_ttk  # noqa: E402

from app.theme import theme_colours, tokens  # noqa: E402

AA = 4.5
# widget state -> the sprite drawn for it (sv_ttk's AccentButton.button element map)
STATES = {
    "rest": ([], "button-accent-rest"),
    "hover": (["active"], "button-accent-hover"),
    "focus": (["focus"], "button-accent-focus"),
    "pressed": (["pressed"], "button-accent-pressed"),
}


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    yield r
    r.destroy()


def _linear(channel: int) -> float:
    v = channel / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def ratio(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _rgb(root: tk.Tk, colour: str) -> tuple[int, int, int]:
    r, g, b = root.winfo_rgb(colour)
    return r // 257, g // 257, b // 257


def _sprite_fill(root: tk.Tk, theme: str, name: str) -> tuple[int, int, int]:
    folder = os.path.join(os.path.dirname(sv_ttk.__file__), "theme")
    with open(os.path.join(folder, f"sprites_{theme}.tcl"), encoding="utf-8") as f:
        text = f.read()
    m = re.search(rf"\b{re.escape(name)}\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)", text)
    assert m, f"{name} not in sv_ttk's sprite list"
    x, y, w, h = map(int, m.groups())
    sheet = tk.PhotoImage(master=root, file=os.path.join(folder, f"spritesheet_{theme}.png"))
    pixel = sheet.get(x + w // 2, y + h // 2)
    if isinstance(pixel, str):
        pixel = tuple(int(v) for v in pixel.split())
    return int(pixel[0]), int(pixel[1]), int(pixel[2])


def _text_colour(root: tk.Tk, state: list[str]) -> tuple[int, int, int]:
    style = ttk.Style(root)
    return _rgb(root, str(style.lookup("Accent.TButton", "foreground", state)))


def _measure(root: tk.Tk, theme: str, fix: bool = True) -> dict[str, float]:
    sv_ttk.set_theme(theme)
    if fix:
        theme_colours.fix_accent_button(root)
    return {
        name: ratio(_text_colour(root, state), _sprite_fill(root, theme, sprite))
        for name, (state, sprite) in STATES.items()
    }


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_every_state_of_the_primary_button_text_reaches_aa(root, theme) -> None:
    ratios = _measure(root, theme)
    low = {state: round(value, 2) for state, value in ratios.items() if value < AA}
    assert not low, f"{theme}: below {AA}:1 {low} (all: {ratios})"


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_measurement_sees_the_themes_own_low_pressed_text(root, theme) -> None:
    """Negative control: without the app's fix, sv_ttk's pressed text is under AA."""
    ratios = _measure(root, theme, fix=False)
    assert ratios["pressed"] < AA
    assert ratios["rest"] >= AA  # and the resting button was never the problem


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_resting_text_is_not_white_on_light_cyan(root, theme) -> None:
    """The reported "white text on light cyan" is black on #57c8ff in the dark theme."""
    sv_ttk.set_theme(theme)
    theme_colours.fix_accent_button(root)
    text = _text_colour(root, [])
    fill = _sprite_fill(root, theme, "button-accent-rest")
    if theme == "dark":
        assert text == (0, 0, 0) and fill == (87, 200, 255)
    else:
        assert text == (255, 255, 255) and fill == (5, 96, 182)


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_the_fix_keeps_the_disabled_colour_and_is_repeatable(root, theme) -> None:
    sv_ttk.set_theme(theme)
    style = ttk.Style(root)
    before = style.lookup("Accent.TButton", "foreground", ["disabled"])
    theme_colours.fix_accent_button(root)
    theme_colours.fix_accent_button(root)
    assert style.lookup("Accent.TButton", "foreground", ["disabled"]) == before
    pressed = _rgb(root, str(style.lookup("Accent.TButton", "foreground", ["pressed"])))
    assert pressed == _rgb(root, tokens.ACCENT_BUTTON_PRESSED_TEXT)
