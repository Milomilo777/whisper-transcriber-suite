"""The macOS system font for the UI (card C2.73): app.theme.system_fonts.

sv_ttk names Windows-only families ("Segoe UI Variable ..."); on macOS the app asks for the system
font by name instead. Aqua is patched at the module boundary (``app.mac_native.is_aqua``), so the
file runs on every OS. Windows and Linux must keep the exact earlier font names.
"""
from __future__ import annotations

import re
import tkinter as tk
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from app import mac_native
from app.theme import script_fonts, system_fonts

ROOT = Path(__file__).resolve().parent.parent.parent
SV_NAMES = (
    "SunValleyCaptionFont", "SunValleyBodyFont", "SunValleyBodyStrongFont",
    "SunValleyBodyLargeFont", "SunValleySubtitleFont", "SunValleyTitleFont",
    "SunValleyTitleLargeFont", "SunValleyDisplayFont",
)


class FakeFontTk:
    """A Tcl interpreter with named fonts: ``font names`` / ``font configure`` and nothing else."""

    def __init__(self, fonts: dict[str, dict[str, str]]) -> None:
        self.fonts = fonts
        self.configured: list[tuple[str, tuple[str, ...]]] = []

    @staticmethod
    def splitlist(value: Any) -> tuple[Any, ...]:
        return tuple(value)

    def call(self, *args: Any) -> Any:
        if args[:2] == ("font", "names"):
            return tuple(self.fonts)
        if args[:2] == ("font", "configure"):
            name, options = args[2], args[3:]
            if not options:
                return tuple(x for pair in self.fonts[name].items() for x in pair)
            if len(options) == 1:                       # read one option
                return self.fonts[name][options[0].lstrip("-")]
            self.configured.append((name, tuple(options)))
            for flag, value in zip(options[::2], options[1::2]):
                self.fonts[name][flag.lstrip("-")] = value
            return ""
        raise tk.TclError(f"unexpected call {args!r}")


def _sv_fonts() -> dict[str, dict[str, str]]:
    sizes = {"Caption": -12, "Body": -14, "BodyStrong": -14, "BodyLarge": -18, "Subtitle": -20,
             "Title": -28, "TitleLarge": -40, "Display": -68}
    out: dict[str, dict[str, str]] = {}
    for short, size in sizes.items():
        strong = short in ("BodyStrong", "Subtitle", "Title", "TitleLarge", "Display")
        out[f"SunValley{short}Font"] = {
            "family": "Segoe UI Variable Static Text" + (" Semibold" if strong else ""),
            "size": str(size), "weight": "normal"}
    return out


def _root(fonts: dict[str, dict[str, str]]) -> Any:
    return SimpleNamespace(tk=FakeFontTk(fonts))


@pytest.fixture
def aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: True)


@pytest.fixture
def not_aqua(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)


# --------------------------------------------------------------------- the theme fonts

def test_aqua_theme_fonts_take_the_system_family_and_keep_their_sizes(aqua: None) -> None:
    fonts = _sv_fonts()
    sizes = {n: f["size"] for n, f in fonts.items()}
    root = _root(fonts)
    assert system_fonts.apply(root) is True
    for name, font in fonts.items():
        assert font["family"] == system_fonts.SYSTEM_UI_FAMILY, name
        assert font["size"] == sizes[name], name   # layout was designed around these pixel sizes


def test_the_semibold_theme_fonts_become_bold_and_the_others_stay_normal(aqua: None) -> None:
    fonts = _sv_fonts()
    system_fonts.apply(_root(fonts))
    bold = {n for n, f in fonts.items() if f["weight"] == "bold"}
    assert bold == {"SunValleyBodyStrongFont", "SunValleySubtitleFont", "SunValleyTitleFont",
                    "SunValleyTitleLargeFont", "SunValleyDisplayFont"}


def test_applying_twice_changes_nothing_the_second_time(aqua: None) -> None:
    root = _root(_sv_fonts())
    assert system_fonts.apply(root) is True
    root.tk.configured.clear()
    assert system_fonts.apply(root) is False
    assert root.tk.configured == []


def test_a_theme_without_some_fonts_is_fine(aqua: None) -> None:
    fonts = {"SunValleyBodyFont": _sv_fonts()["SunValleyBodyFont"]}
    root = _root(fonts)
    assert system_fonts.apply(root) is True
    assert list(fonts) == ["SunValleyBodyFont"]
    assert system_fonts.apply(_root({})) is False


def test_other_systems_get_no_font_calls_at_all(not_aqua: None) -> None:
    root = _root(_sv_fonts())
    assert system_fonts.apply(root) is False
    assert root.tk.configured == []
    assert root.tk.fonts["SunValleyBodyFont"]["family"] == "Segoe UI Variable Static Text"


def test_a_font_that_cannot_be_configured_does_not_stop_the_rest(aqua: None) -> None:
    class Flaky(FakeFontTk):
        def call(self, *args: Any) -> Any:
            if args[:3] == ("font", "configure", "SunValleyCaptionFont") and len(args) > 4:
                raise tk.TclError("boom")
            return super().call(*args)

    fonts = _sv_fonts()
    root = SimpleNamespace(tk=Flaky(fonts))
    assert system_fonts.apply(root) is True
    assert fonts["SunValleyBodyFont"]["family"] == system_fonts.SYSTEM_UI_FAMILY


def test_theme_fonts_are_applied_by_apply_theme_fonts_after_every_theme_switch(
        monkeypatch: pytest.MonkeyPatch, aqua: None) -> None:
    calls: list[str] = []
    monkeypatch.setattr(system_fonts, "apply", lambda _root: calls.append("system") or False)
    monkeypatch.setattr(script_fonts, "scale_theme_fonts", lambda _root: calls.append("scale") or False)
    monkeypatch.setattr(script_fonts, "fix_tree_font", lambda _root: calls.append("tree") or False)
    monkeypatch.setattr(script_fonts, "_on_windows", lambda: False)
    script_fonts.apply_theme_fonts(SimpleNamespace())  # type: ignore[arg-type]
    assert calls == ["system", "scale", "tree"]


def test_per_script_fonts_stay_windows_only(monkeypatch: pytest.MonkeyPatch, aqua: None) -> None:
    # On macOS the system font itself falls back per script (probe: .SF Arabic, .PingFang SC, ...).
    monkeypatch.setattr(script_fonts, "_on_windows", lambda: False)
    monkeypatch.setattr(script_fonts, "installed_families", lambda _w: frozenset({"Nirmala UI"}))
    persian = chr(0x641) + chr(0x627) + chr(0x631) + chr(0x633) + chr(0x6CC)
    assert script_fonts.family_for(persian, "fa", installed=frozenset({"Nirmala UI"})) is None
    assert script_fonts.family_for("සිං", "si", installed=frozenset()) is None


# --------------------------------------------------------------- hard-coded UI fonts

@pytest.mark.parametrize(("family", "size", "style", "expected"), [
    ("Segoe UI", 10, "bold", (system_fonts.SYSTEM_UI_FAMILY, 10, "bold")),
    ("Segoe UI", 8, "", (system_fonts.SYSTEM_UI_FAMILY, 8)),
    ("Segoe UI Semibold", 20, "", (system_fonts.SYSTEM_UI_FAMILY, 20, "bold")),
    ("Segoe UI Semibold", 11, "italic", (system_fonts.SYSTEM_UI_FAMILY, 11, "bold italic")),
])
def test_ui_font_on_aqua(aqua: None, family: str, size: int, style: str, expected: tuple[Any, ...]) -> None:
    assert system_fonts.ui_font(SimpleNamespace(), family, size, style) == expected


@pytest.mark.parametrize(("family", "size", "style", "expected"), [
    ("Segoe UI", 10, "bold", ("Segoe UI", 10, "bold")),
    ("Segoe UI", 8, "", ("Segoe UI", 8)),
    ("Segoe UI Semibold", 20, "", ("Segoe UI Semibold", 20)),
    ("Segoe UI Semibold", 11, "italic", ("Segoe UI Semibold", 11, "italic")),
])
def test_ui_font_elsewhere_is_exactly_the_old_tuple(not_aqua: None, family: str, size: int, style: str,
                                                    expected: tuple[Any, ...]) -> None:
    assert system_fonts.ui_font(SimpleNamespace(), family, size, style) == expected


def test_no_widget_hard_codes_a_segoe_font_any_more() -> None:
    """The four canvas/label sites go through ``ui_font`` so macOS gets the system font."""
    for path in sorted((ROOT / "app" / "widgets").glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if re.search(r'font=\(\s*"Segoe', line):
                pytest.fail(f"{path.name}:{number} still hard-codes a Segoe font: {line.strip()}")


# ---------------------------------------------------- real Tk with sv_ttk (aqua patched)

@pytest.fixture
def themed_root():
    try:
        root = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    root.withdraw()
    try:
        import sv_ttk
        sv_ttk.set_theme("light")
        yield root
    finally:
        root.destroy()


def test_real_sv_ttk_fonts_are_switched_on_aqua_and_untouched_elsewhere(
        monkeypatch: pytest.MonkeyPatch, themed_root: tk.Tk) -> None:
    def state() -> dict[str, tuple[str, str, str]]:
        call = themed_root.tk.call
        return {n: (str(call("font", "configure", n, "-family")),
                    str(call("font", "configure", n, "-size")),
                    str(call("font", "configure", n, "-weight"))) for n in SV_NAMES}

    before = state()
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: False)
    assert system_fonts.apply(themed_root) is False
    assert state() == before                                    # Windows/Linux: byte for byte
    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: True)
    assert system_fonts.apply(themed_root) is True
    after = state()
    for name in SV_NAMES:
        family, size, weight = after[name]
        assert family == system_fonts.SYSTEM_UI_FAMILY
        assert size == before[name][1]
        assert weight == ("bold" if "Semibold" in before[name][0] else "normal")


# ----------------------------- the real call sites (smtv hero, audio meter) with aqua forced

def _text_fonts(canvas: tk.Canvas) -> list[str]:
    return [str(canvas.itemcget(item, "font")) for item in canvas.find_all() if canvas.type(item) == "text"]


@pytest.mark.parametrize(("is_aqua", "expect_system"), [(True, True), (False, False)])
def test_smtv_hero_and_audio_meter_use_the_system_font_only_on_aqua(
        monkeypatch: pytest.MonkeyPatch, themed_root: tk.Tk, is_aqua: bool, expect_system: bool) -> None:
    pytest.importorskip("PIL.ImageTk")
    from app.widgets import audio_visualizer, smtv_tab

    monkeypatch.setattr(mac_native, "is_aqua", lambda _w: is_aqua)
    state = smtv_tab._TabState(SimpleNamespace())
    try:
        hero = smtv_tab._build_hero(SimpleNamespace(), state, themed_root)
        state.redraw_hero()
        hero_fonts = _text_fonts(hero)
        viz = audio_visualizer.AudioVisualizer(tk.Frame(themed_root))
        viz.frame.pack()
        themed_root.update()
        meter_fonts = _text_fonts(viz.canvas)
    finally:
        state._pool.shutdown(wait=False)
    assert len(hero_fonts) == 3 and meter_fonts
    for font in hero_fonts + meter_fonts:
        assert (system_fonts.SYSTEM_UI_FAMILY in font) is expect_system, font
        assert ("Segoe" in font) is not expect_system, font
