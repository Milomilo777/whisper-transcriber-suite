"""WCAG contrast of the colour tokens, and of the device badge as the app really colours it."""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from app.theme import tokens


def _linear(channel: int) -> float:
    v = channel / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(hex_str: str) -> float:
    hex_str = hex_str.lstrip("#")
    if len(hex_str) == 3:
        hex_str = "".join(c + c for c in hex_str)
    r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
    return 0.2126 * _linear(r) + 0.7152 * _linear(g) + 0.0722 * _linear(b)


def ratio(a: str, b: str) -> float:
    hi, lo = sorted((_luminance(a), _luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_audit_light():
    # Light theme tests vs Light panel (#fafafa)
    bg = tokens.LIGHT_PANEL

    # 4.5:1 text requirements
    assert ratio(tokens.LINK, bg) >= 4.5
    assert ratio(tokens.TEXT_MUTED, bg) >= 4.5
    assert ratio(tokens.SUCCESS_TEXT, bg) >= 4.5
    assert ratio(tokens.WARNING_TEXT, bg) >= 4.5
    assert ratio(tokens.DANGER_TEXT, bg) >= 4.5
    assert ratio(tokens.CHIP_GPU, bg) >= 4.5
    assert ratio(tokens.CHIP_CPU, bg) >= 4.5
    assert ratio(tokens.SUCCESS_STRONG, bg) >= 4.5
    assert ratio(tokens.WARNING_STRONG, bg) >= 4.5
    assert ratio(tokens.DANGER_STRONG, bg) >= 4.5
    assert ratio(tokens.TEXT_MISSING, bg) >= 4.5

    # UI parts / icons / large text (>= 3:1)
    assert ratio(tokens.DANGER_ICON, bg) >= 3.0
    assert ratio(tokens.TEXT_SUBTLE, bg) >= 3.0


def test_contrast_audit_tinted_rows():
    # Light theme text on tinted rows
    for r in [tokens.ROW_ACTIVE, tokens.ROW_SUSPECT, tokens.ROW_WARN]:
        assert ratio(tokens.WARNING_STRONG, r) >= 4.5
        assert ratio(tokens.TEXT_MISSING, r) >= 4.5
        assert ratio(tokens.TEXT_MUTED, r) >= 4.5
        assert ratio(tokens.SUCCESS_STRONG, r) >= 4.5
        assert ratio(tokens.DANGER_STRONG, r) >= 4.5

    # Dark variants on dark tinted rows
    for r in [tokens.ROW_ACTIVE, tokens.ROW_SUSPECT, tokens.ROW_WARN]:
        dark_r = tokens.DARK_VARIANTS[r]
        assert ratio(tokens.DARK_VARIANTS[tokens.WARNING_STRONG], dark_r) >= 4.5
        assert ratio(tokens.DARK_VARIANTS[tokens.TEXT_MISSING], dark_r) >= 4.5
        assert ratio(tokens.DARK_VARIANTS[tokens.TEXT_MUTED], dark_r) >= 4.5
        assert ratio(tokens.DARK_VARIANTS[tokens.SUCCESS_STRONG], dark_r) >= 4.5
        assert ratio(tokens.DARK_VARIANTS[tokens.DANGER_STRONG], dark_r) >= 4.5


def test_contrast_audit_chip_palettes():
    # Chip palettes contrast
    for theme, p in tokens.CHIP_PALETTES.items():
        bg_panel = tokens.LIGHT_PANEL if theme == "light" else tokens.DARK_PANELS[0]
        assert ratio(p["normal_border"], bg_panel) >= 3.0
        assert ratio(p["hover_border"], bg_panel) >= 3.0
        assert ratio(p["toggle_fg"], bg_panel) >= 4.5
        assert ratio(p["ring"], bg_panel) >= 3.0

        assert ratio(p["normal_fg"], p["normal_bg"]) >= 4.5
        assert ratio(p["hover_fg"], p["hover_bg"]) >= 4.5
        assert ratio(p["selected_fg"], p["selected_bg"]) >= 4.5


class _FakeLabel:
    def __init__(self) -> None:
        self.options: dict[str, Any] = {}

    def configure(self, **kw: Any) -> None:
        self.options.update(kw)


@pytest.mark.parametrize(
    ("theme", "panel"), [("light", tokens.LIGHT_PANEL), ("dark", tokens.DARK_PANELS[0])]
)
@pytest.mark.parametrize("kind", ["gpu", "cpu", "cpu_downgraded"])
def test_device_badge_colour_meets_wcag_aa(monkeypatch, theme: str, panel: str, kind: str) -> None:
    """The colour App.apply_device_badge really sets reads at 4.5:1 on the theme's panel.

    Calls the real method on a stand-in ``self`` (no Tk window), so a badge colour that skips
    ``tokens.themed`` (the light amber on the dark panel, or the reverse) fails here.
    """
    from app.app import App

    monkeypatch.setattr(tokens, "_theme", theme)
    label = _FakeLabel()
    fake = SimpleNamespace(
        device_badge_var=SimpleNamespace(set=lambda _text: None),
        device_badge_labels=[label],
        device_badge_tip="",
    )
    App.apply_device_badge(fake, "CPU", kind, {"device": "cpu"})  # type: ignore[arg-type]
    colour = label.options["foreground"]
    assert ratio(colour, panel) >= 4.5, (theme, kind, colour, panel)


@pytest.mark.parametrize(("kind", "token"), [
    ("cpu", tokens.TEXT_MUTED), ("cpu_downgraded", tokens.CHIP_CPU), ("gpu", tokens.CHIP_GPU),
])
def test_a_plain_cpu_badge_is_grey_not_a_warning(monkeypatch, kind: str, token: str) -> None:
    """Amber read as a warning on every CPU-only computer, where there is nothing to fix (deep
    review, 2026-10-21): plain CPU is grey; amber stays for a GPU that could not be used."""
    from app.app import App

    monkeypatch.setattr(tokens, "_theme", "light")
    label = _FakeLabel()
    fake = SimpleNamespace(device_badge_var=SimpleNamespace(set=lambda _text: None),
                           device_badge_labels=[label], device_badge_tip="")
    App.apply_device_badge(fake, "CPU", kind, {"device": "cpu"})  # type: ignore[arg-type]
    assert label.options["foreground"] == tokens.themed(token)
