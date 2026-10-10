"""Text size at 125/150 % scaling, dark-theme colours and window fit (card C2.61).

Display scaling is simulated with ``tk scaling`` (Tk derives ``winfo_fpixels`` from it, and the
app's scale factor from that); a real 125/150 % Windows display is a manual check.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import font as tkfont  # noqa: E402
from tkinter import ttk  # noqa: E402

from app import dpi  # noqa: E402
from app.theme import script_fonts, theme_colours, tokens  # noqa: E402

_REPO = Path(__file__).resolve().parents[2]
_APP = _REPO / "app"


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as e:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {e}")
    r.withdraw()
    # ``tk scaling`` belongs to the display, not to this root: a test that sets it (_scale) would
    # otherwise leave 125/150 % behind for every later test that builds a window.
    scaling = r.tk.call("tk", "scaling")
    yield r
    try:
        r.tk.call("tk", "scaling", scaling)
    finally:
        r.destroy()


@pytest.fixture(autouse=True)
def _light_tokens(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(tokens, "_theme", "light")
    monkeypatch.setattr(dpi, "_process_factor", 1.0)


def _scale(root: Any, factor: float) -> None:
    root.tk.call("tk", "scaling", factor * 96 / 72)


def _sv_ttk(root: Any, theme: str = "dark") -> None:
    sv_ttk = pytest.importorskip("sv_ttk")
    sv_ttk.set_theme(theme, root)


# ------------------------------------------------------------------ S10-1 theme fonts

@pytest.mark.parametrize("factor, size", [(1.0, -14), (1.25, -18), (1.5, -21)])
def test_theme_fonts_grow_with_the_scale(root, factor, size) -> None:
    _sv_ttk(root)
    _scale(root, factor)
    script_fonts.scale_theme_fonts(root, factor)
    body = tkfont.nametofont("SunValleyBodyFont", root=root)
    assert int(body.cget("size")) == size
    assert int(tkfont.nametofont("SunValleyCaptionFont", root=root).cget("size")) == round(-12 * factor)
    rows = int(str(ttk.Style(root).lookup("Treeview", "rowheight")))
    assert rows == body.metrics("linespace") + 3


def test_theme_fonts_scale_once_per_interpreter(root) -> None:
    """A theme switch calls this again: the size must not grow a second time."""
    _sv_ttk(root)
    for _ in range(3):
        script_fonts.scale_theme_fonts(root, 1.5)
    assert int(tkfont.nametofont("SunValleyBodyFont", root=root).cget("size")) == -21
    script_fonts.scale_theme_fonts(root, 1.0)
    assert int(tkfont.nametofont("SunValleyBodyFont", root=root).cget("size")) == -14


def test_ttk_text_keeps_pace_with_point_sized_text(root) -> None:
    """The measured gap of S10-1: ttk 16 pixels against 28 for 10-point text at 150 %."""
    if sys.platform != "win32":
        pytest.skip("the factor is 1.0 off Windows")
    _sv_ttk(root)
    _scale(root, 1.5)
    script_fonts.apply_theme_fonts(root)
    body = tkfont.nametofont("SunValleyBodyFont", root=root).metrics("linespace")
    points = tkfont.Font(root=root, family="Segoe UI", size=10).metrics("linespace")
    assert body >= 0.8 * points
    tree_font = str(ttk.Style(root).lookup("Treeview", "font"))
    tree_line = int(root.tk.call("font", "metrics", tree_font, "-linespace"))
    assert int(str(ttk.Style(root).lookup("Treeview", "rowheight"))) >= tree_line + 3


def test_point_sized_theme_fonts_are_left_alone(root) -> None:
    root.tk.call("font", "create", "SunValleyBodyFont", "-family", "Arial", "-size", 10)
    assert script_fonts.scale_theme_fonts(root, 1.5) is False
    assert int(root.tk.call("font", "configure", "SunValleyBodyFont", "-size")) == 10


# ----------------------------------------------------------------- S10-3 / A1 kana marks

@pytest.mark.parametrize("mark", [0x30FB, 0x30FC, 0x309B, 0x309C, 0xFF70, 0xFF9E, 0xFF9F])
def test_marks_shared_with_chinese_do_not_make_han_japanese(mark: int) -> None:
    text = "約翰" + chr(mark) + "史密斯"  # a Chinese name with the mark
    assert script_fonts.text_script(text) == "han"
    assert script_fonts.font_key(text, "zh-hant") == "zh-hant"
    assert script_fonts.font_key(text, "zh-CN") == "zh-hans"


def test_real_kana_still_makes_the_line_japanese() -> None:
    hiragana_no = chr(0x306E)
    assert script_fonts.font_key("日本語" + hiragana_no, "zh") == "ja"
    # A katakana word with the prolonged-sound mark is still Japanese.
    assert script_fonts.font_key("コーヒー") == "ja"


# -------------------------------------------------------------------- S10-2 dark tokens

def _lum(colour: str) -> float:
    c = colour.lstrip("#")
    parts = [int(c[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in parts]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def _contrast(a: str, b: str) -> float:
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_contrast_helper_is_not_blind() -> None:
    assert _contrast("#000000", "#ffffff") == pytest.approx(21.0)
    # The S10-2 measurement: conf_low on the dark panel before the fix.
    assert _contrast("#a00000", "#1c1c1c") == pytest.approx(2.02, abs=0.01)


def test_dark_text_variants_meet_wcag_aa_on_dark_panels() -> None:
    tints = set(tokens.ROW_TINTS)
    for light, dark in tokens.DARK_VARIANTS.items():
        if light in tints:
            continue
        for panel in tokens.DARK_PANELS:
            assert _contrast(dark, panel) >= 4.5, (light, dark, panel)


def test_dark_row_tints_keep_text_readable() -> None:
    texts = ["#fafafa"] + [tokens.DARK_VARIANTS[c] for c in
                           (tokens.SUCCESS_STRONG, tokens.WARNING_STRONG, tokens.DANGER_STRONG)]
    for tint in tokens.ROW_TINTS:
        for text in texts:
            assert _contrast(text, tokens.DARK_VARIANTS[tint]) >= 4.5, (tint, text)


def test_light_link_meets_wcag_aa() -> None:
    assert _contrast(tokens.LINK, tokens.LIGHT_PANEL) >= 4.5


def test_variants_can_always_be_swapped_back() -> None:
    lights, darks = set(tokens.DARK_VARIANTS), set(tokens.DARK_VARIANTS.values())
    assert not lights & darks
    assert len(darks) == len(tokens.DARK_VARIANTS)
    assert all(c == c.lower() and re.fullmatch(r"#[0-9a-f]{6}", c) for c in lights | darks)


def test_themed_follows_the_theme() -> None:
    assert tokens.themed(tokens.DANGER_STRONG) == tokens.DANGER_STRONG
    tokens.set_theme("dark")
    assert tokens.themed(tokens.DANGER_STRONG) == "#f4a6a6"
    assert tokens.themed(tokens.TEXT_SUBTLE) == tokens.TEXT_SUBTLE  # no variant needed
    assert tokens.themed("#f4a6a6", "light") == tokens.DANGER_STRONG


def test_recolour_swaps_widgets_and_tags(root) -> None:
    label = ttk.Label(root, text="x", foreground=tokens.themed(tokens.TEXT_MUTED))
    other = ttk.Label(root, text="y", foreground="red")
    tree = ttk.Treeview(root)
    tree.tag_configure("conf_low", foreground=tokens.themed(tokens.DANGER_STRONG))
    tree.tag_configure("suspect", background=tokens.themed(tokens.ROW_SUSPECT))
    text = tk.Text(root)
    text.tag_configure("link", foreground=tokens.themed(tokens.LINK))

    assert theme_colours.apply(root, "dark") == 4
    assert tokens.current_theme() == "dark"
    assert str(label.cget("foreground")) == tokens.DARK_VARIANTS[tokens.TEXT_MUTED]
    assert str(other.cget("foreground")) == "red"
    assert str(tree.tag_configure("conf_low", "foreground")) == tokens.DARK_VARIANTS[tokens.DANGER_STRONG]
    assert str(tree.tag_configure("suspect", "background")) == tokens.DARK_VARIANTS[tokens.ROW_SUSPECT]
    assert str(text.tag_cget("link", "foreground")) == tokens.DARK_VARIANTS[tokens.LINK]
    # New widgets made now get the dark colour straight away.
    assert tokens.themed(tokens.TEXT_MUTED) == tokens.DARK_VARIANTS[tokens.TEXT_MUTED]

    assert theme_colours.apply(root, "light") == 4
    assert str(label.cget("foreground")) == tokens.TEXT_MUTED
    assert str(tree.tag_configure("suspect", "background")) == tokens.ROW_SUSPECT
    assert theme_colours.apply(root, "light") == 0


# ------------------------------------------------------- S10-4 first-run window fit

@pytest.mark.parametrize("dpi_value, work", [
    (144, (0, 0, 1920, 1020)),     # 150 %, taskbar at the bottom
    (120, (0, 0, 1920, 1032)),     # 125 %
    (144, (0, 60, 1920, 1020)),    # 150 %, taskbar at the top
    (96, (1920, 0, 1366, 728)),    # second monitor, 1366x768 at 100 %
])
def test_first_run_window_stays_inside_the_work_area(monkeypatch, dpi_value, work) -> None:
    import types

    from app.app import App

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(dpi, "_windows_work_area", lambda _w: work)
    calls: list = []
    fake = types.SimpleNamespace(
        winfo_fpixels=lambda _s: dpi_value,
        winfo_screenwidth=lambda: 1920, winfo_screenheight=lambda: 1080,
        geometry=lambda g=None: calls.append(g),
        state=lambda s: calls.append(("state", s)),
    )
    App._apply_default_geometry(fake)  # type: ignore[arg-type]
    w, h, x, y = map(int, re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", calls[0]).groups())
    ax, ay, aw, ah = work
    title = round(32 * dpi_value / 96)
    assert ax <= x and x + w <= ax + aw
    assert ay <= y and y + title + h <= ay + ah


# ------------------------------------------------------------ A6 no colours outside tokens

_LITERAL = re.compile(r"""(foreground|background|fg|bg|fill)\s*=\s*["']#[0-9a-fA-F]{3,6}["']""")


def _variant_names() -> list[str]:
    return sorted(n for n in dir(tokens) if n.isupper()
                  and isinstance(getattr(tokens, n), str) and getattr(tokens, n) in tokens.DARK_VARIANTS)


def _unthemed_reads(source: str) -> list[int]:
    pattern = re.compile(r"(?<!themed\()tokens\.(" + "|".join(_variant_names()) + r")\b")
    hits = []
    for number, line in enumerate(source.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("#") or re.match(r"^_[A-Z_]+ = tokens\.", stripped):
            continue  # module constants are read through themed() where they are used
        if pattern.search(line) and not re.match(r'^"\w+": tokens\.', stripped):
            hits.append(number)
    return hits


def _app_sources():
    for path in sorted(_APP.rglob("*.py")):
        if path.relative_to(_APP).parts[0] != "theme":
            yield path, path.read_text(encoding="utf-8")


def test_no_literal_colour_in_a_widget_call() -> None:
    found = [f"{p.relative_to(_REPO).as_posix()}:{n}"
             for p, src in _app_sources()
             for n, line in enumerate(src.splitlines(), 1) if _LITERAL.search(line)]
    assert found == []


def test_dark_variant_colours_are_read_through_themed() -> None:
    found = [f"{p.relative_to(_REPO).as_posix()}:{n}" for p, src in _app_sources()
             for n in _unthemed_reads(src)]
    assert found == []


def test_the_colour_scans_are_not_blind() -> None:
    assert _LITERAL.search('ttk.Label(body, text=note, foreground="#666")')
    assert _unthemed_reads("x = ttk.Label(p, foreground=tokens.LINK)\n") == [1]
    assert _unthemed_reads("x = ttk.Label(p, foreground=tokens.themed(tokens.LINK))\n") == []


# ----------------------------------------------- item 6 viewer toolbar fits at every scale

def _segments() -> list[dict[str, Any]]:
    return [{"start": 0.0, "end": 1.25, "text": "Hello world"}]


@pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true",
    reason=("measures real font widths: the hosted runners ship other fonts and screen metrics than"
            " the machines people use, so the result there says nothing about the app; this check"
            " runs locally and on the macOS test machines"),
)
@pytest.mark.parametrize("factor", [1.0, 1.25, 1.5])
def test_viewer_toolbars_fit_the_window(root, tmp_path, monkeypatch, factor) -> None:
    from app.dialogs import transcript_viewer as tv
    from core import subtitle_edit
    from core.transcriber import _write_outputs

    monkeypatch.setattr(subtitle_edit, "is_supported", lambda: True)
    monkeypatch.setattr(sys, "platform", "win32")  # scale_factor follows tk scaling
    # python-vlc reads Windows-only environment variables once sys.platform says win32
    # (KeyError 'ProgramFiles' on a Mac); the toolbars do not depend on a player.
    monkeypatch.setattr(tv, "_try_load_vlc", lambda: (None, "no player in this test"))
    _sv_ttk(root, "light")
    _scale(root, factor)
    script_fonts.scale_theme_fonts(root, factor)
    dpi.remember_scale(root)
    written = _write_outputs(str(tmp_path / "talk"), _segments(), str(tmp_path / "talk.mp4"), ["json"])
    viewer = tv.TranscriptViewer(root, next(p for p in written if p.endswith(".json")))
    viewer.withdraw()
    try:
        viewer.update_idletasks()
        width = dpi.scaled_size(viewer, 1180, 720)[0]  # the viewer's opening size
        outer = viewer.winfo_children()[0]
        bars = [w for w in outer.winfo_children()
                if w.winfo_class() == "TFrame"
                and any(c.winfo_class() == "TButton" for c in w.winfo_children())]
        assert len(bars) >= 2
        for bar in bars:
            # outer has 8 pixels of padding on each side
            assert bar.winfo_reqwidth() <= width - 16, [c.cget("text") for c in bar.winfo_children()
                                                         if c.winfo_class() == "TButton"]
    finally:
        viewer._dirty = False
        viewer._on_close()


# ------------------------------------------- Advanced: side column and window fit per scale

@pytest.mark.parametrize("factor", [1.0, 1.25, 1.5])
def test_advanced_nav_links_fit_and_window_stays_in_the_work_area(root, monkeypatch, tmp_path,
                                                                   factor) -> None:
    from app.dialogs import advanced as adv
    from core.config import DEFAULT_CONFIG

    monkeypatch.setattr(adv.AdvancedDialog, "grab_set", lambda self, *a, **k: None)
    monkeypatch.setattr(sys, "platform", "win32")  # scale_factor follows tk scaling
    work = (0, 0, 1920, 1040)
    monkeypatch.setattr(dpi, "_windows_work_area", lambda _w: work)
    _sv_ttk(root, "light")
    _scale(root, factor)
    script_fonts.scale_theme_fonts(root, factor)
    dpi.remember_scale(root)
    cfg = dict(DEFAULT_CONFIG)
    cfg["hub_folder"] = str(tmp_path / "models")
    root.app_config = cfg
    root.log = lambda _m: None
    placed: list[str] = []
    monkeypatch.setattr(adv.AdvancedDialog, "geometry",
                        lambda self, g=None: placed.append(g) if g else "1x1+0+0")
    dlg = adv.AdvancedDialog(root)
    try:
        dlg.update_idletasks()
        nav = dlg._nav_frame
        width = int(nav.cget("width"))
        for link in dlg._nav_links:
            if link.winfo_class() == "TLabel":
                assert link.winfo_reqwidth() <= width, link.cget("text")
        w, h, x, y = map(int, re.match(r"(\d+)x(\d+)\+(\d+)\+(\d+)", placed[-1]).groups())
        assert x + w <= work[2]
        assert y + round(32 * factor) + h <= work[3]
    finally:
        dlg.destroy()


# ------------------------------------------------------------- optional A2 / A7

def test_a_skin_tone_stays_with_its_emoji() -> None:
    waving, tone = chr(0x1F44B), chr(0x1F3FD)
    line = "ab" + waving + tone + "cd"
    assert script_fonts._cluster_boundary(line, line.index(tone)) is False
    assert script_fonts._cluster_boundary(line, line.index("c")) is True


def test_typing_retags_once_per_pause(root, monkeypatch) -> None:
    import types

    from app.widgets import voice_clone_tab as vct

    calls: list[int] = []
    monkeypatch.setattr(vct, "_retag_text", lambda _app: calls.append(1))
    text = tk.Text(root)
    app = types.SimpleNamespace(vc_text=text)
    for _ in range(5):
        vct._schedule_retag(app)
    assert calls == []
    root.after(vct._RETAG_DELAY_MS + 100, root.quit)
    root.mainloop()
    assert calls == [1]
    assert app._vc_retag_after is None


def test_tooltip_wrap_grows_with_the_scale(root, monkeypatch) -> None:
    from app.widgets import tooltip

    monkeypatch.setattr(dpi, "_process_factor", 1.5)
    label = ttk.Label(root, text="x")
    tooltip.bind_tooltip(label, "some help", delay_ms=0)
    label.event_generate("<Enter>")
    root.update()
    tips = [w for w in label.winfo_children() if w.winfo_class() == "Toplevel"]
    assert tips, "the tooltip did not open"
    inner = tips[-1].winfo_children()[0]
    assert int(str(inner.cget("wraplength"))) == round(tooltip._WRAP * 1.5)
