"""The rounded program chips of the Supreme Master TV tab (app/widgets/chip_cloud.py)."""
import tkinter as tk

import pytest

from app.theme import tokens
from app.widgets import chip_cloud as cc

LABELS = [f"Program number {i}" for i in range(24)]


@pytest.fixture(scope="module")
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    r.geometry("900x300")
    yield r
    r.destroy()


@pytest.fixture
def cloud(root):
    picked: list[str] = []
    w = cc.ChipCloud(root, LABELS, picked.append)
    w.pack(fill="x")
    root.update()
    w.picked = picked  # type: ignore[attr-defined]
    yield w
    w.destroy()


def _contrast(a: str, b: str) -> float:
    def lum(h: str) -> float:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_flow_layout_wraps_and_keeps_an_oversized_item_on_its_own_row():
    pos = cc.flow_layout([40, 40, 40, 500, 10], avail=125, gap=5, row_h=20)
    assert pos[0] == (0, 0) and pos[1] == (45, 0)
    assert pos[2] == (0, 25)          # third item does not fit on row 1
    assert pos[3] == (0, 50)          # too wide: alone on its row
    assert pos[4] == (0, 75)


def test_collapsed_shows_one_row_ending_in_all_programs_and_expands_to_all(cloud, root):
    chips = cloud._chips
    assert chips[-1].toggle and chips[-1].text == cc.MORE_TEXT == "All programs ▾"
    shown = len(chips) - 1
    assert 0 < shown < len(LABELS)
    assert len({c.y for c in chips}) == 1  # one row
    cloud.activate(len(chips) - 1)
    root.update()
    labels = [c.label for c in cloud._chips if not c.toggle]
    assert labels == LABELS and cloud._chips[-1].text == cc.LESS_TEXT == "Show less ▴"
    assert len({c.y for c in cloud._chips}) > 1  # wrapped onto several rows
    cloud.activate(len(cloud._chips) - 1)
    assert not cloud.expanded


def test_the_all_programs_control_is_ghost_text_not_a_chip(cloud, root):
    last = len(cloud._chips) - 1
    tag = f"chip{last}"
    kinds = [cloud.type(i) for i in cloud.find_withtag(tag)]
    assert kinds == ["text"]  # no pill image: no fill, no border
    assert cloud.itemcget(cloud.find_withtag(tag)[0], "fill") == cloud.palette()["toggle_fg"]
    # Hovered, it is underlined; a chip is never underlined.
    cloud.hover_index = last
    cloud.redraw()
    assert str(tkfont_of(cloud, tag).actual("underline")) in ("1", "True")
    cloud.hover_index = 0
    cloud.redraw()
    assert str(tkfont_of(cloud, "chip0").actual("underline")) in ("0", "False")


def test_ghost_control_has_air_after_the_last_chip_on_its_row(cloud, monkeypatch):
    monkeypatch.setattr(cc, "scale_factor", lambda _w: 1.0)
    cloud.redraw()
    chips = cloud._chips
    gap = chips[-1].x - (chips[-2].x + chips[-2].w)
    assert gap == cc.GAP + cc.GHOST_PAD


def tkfont_of(cloud, tag):
    import tkinter.font as tkfont
    item = [i for i in cloud.find_withtag(tag) if cloud.type(i) == "text"][0]
    return tkfont.Font(root=cloud, font=cloud.itemcget(item, "font"))


def test_chips_are_32px_tall_at_96_dpi_with_a_readable_gap(cloud, root, monkeypatch):
    monkeypatch.setattr(cc, "scale_factor", lambda _w: 1.0)
    cloud.redraw()
    assert cc.CHIP_H == 32 and cc.PAD_X == 14 and cc.GAP == 8
    assert int(float(cloud.cget("height"))) == 32 + 2 * cc.MARGIN  # one row plus the ring room
    chips = [c for c in cloud._chips if not c.toggle]
    assert chips[1].x - (chips[0].x + chips[0].w) == cc.GAP
    img = cloud.find_withtag("chip0")[0]
    assert cloud.type(img) == "image"


def test_selected_chip_gets_a_check_mark_prefix(cloud, root):
    plain = cloud._chips[2].w
    cloud.activate(2)
    root.update()
    texts = [cloud.itemcget(i, "text") for i in cloud.find_withtag("chip2") if cloud.type(i) == "text"]
    assert texts == [cc.CHECK + LABELS[2]] and cc.CHECK == "✓ "
    assert cloud._chips[2].w > plain  # room was made for it
    other = [cloud.itemcget(i, "text") for i in cloud.find_withtag("chip3") if cloud.type(i) == "text"]
    assert other == [LABELS[3]]


def test_keyboard_reaches_the_all_programs_control(cloud, root):
    cloud.focus_force()
    cloud.event_generate("<FocusIn>")  # another window may hold the real focus on a busy desktop
    root.update()
    cloud.event_generate("<End>")
    cloud.event_generate("<space>")
    root.update()
    assert cloud.expanded and cloud.picked == []


def test_clicking_a_chip_runs_the_command_and_marks_it_selected(cloud):
    cloud.activate(2)
    assert cloud.picked == [LABELS[2]] and cloud.selected == LABELS[2]
    pal = cloud.palette()
    assert cloud._chips[2].bg == pal["selected_bg"]
    assert cloud.find_withtag("chip2")  # drawn


def test_keyboard_moves_the_focus_and_activates(cloud, root):
    cloud.focus_force()
    root.update()
    cloud.event_generate("<Right>")
    cloud.event_generate("<Return>")
    root.update()
    assert cloud.picked == [LABELS[1]]


def test_redraw_follows_the_theme(cloud, monkeypatch):
    monkeypatch.setattr(tokens, "current_theme", lambda: "dark")
    cloud.redraw()
    assert cloud._chips[0].bg == cc.PALETTES["dark"]["normal_bg"]


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chip_text_is_readable_in_every_state(theme):
    pal = cc.PALETTES[theme]
    for state in ("normal", "hover", "selected"):
        assert _contrast(pal[f"{state}_fg"], pal[f"{state}_bg"]) >= 4.5, (theme, state)
    # The ghost control is text on the bare panel.
    assert _contrast(pal["toggle_fg"], _panel(theme)) >= 4.5, theme


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_chip_borders_and_fills_stand_out_from_the_panel(theme):
    """WCAG 1.4.11: the edge that shows a chip is a control reaches 3:1 against the panel."""
    pal = cc.PALETTES[theme]
    panel = _panel(theme)
    assert _contrast(pal["normal_border"], panel) >= 3.0, theme
    assert _contrast(pal["hover_border"], panel) >= 3.0, theme
    assert _contrast(pal["selected_bg"], panel) >= 3.0, theme   # the solid chip has no border
    assert _contrast(pal["ring"], panel) >= 3.0, theme          # keyboard focus ring
    # The review's complaint: a chip fill that is invisible by itself (1.1:1) is not enough.
    assert _contrast(pal["normal_bg"], panel) < 3.0  # fill is a tint; the border does the work


def test_the_contrast_check_is_not_blind():
    # Negative control: the light chips of the previous design fail the border rule.
    assert _contrast("#eef2f4", _panel("light")) < 1.3
    assert _contrast("#ffffff", "#ffffff") == 1.0


def _panel(theme):
    return tokens.LIGHT_PANEL if theme == "light" else tokens.DARK_PANELS[0]


def test_flatten_matches_painting_the_layers_in_order():
    # 50 % black, then 50 % white, painted over a background by hand and as one flattened layer.
    r, g, b, a = cc.flatten([("#000000", 0.5), ("#ffffff", 0.5)])
    for bg in (0, 100, 255):
        by_hand = (bg * 0.5) * 0.5 + 255 * 0.5
        flat = bg * (1 - a / 255) + r * (a / 255)
        assert abs(by_hand - flat) < 1.5
    assert cc.flatten([("#336699", 0.0)])[3] == 0


def test_translucent_pill_has_no_dark_fringe():
    img = cc.render_pill(60, 32, (255, 255, 255, 40), (255, 255, 255, 140), 1)
    # Every pixel with some alpha is white: premultiplied scaling keeps the edge colour.
    pixels = img.load()
    assert all(pixels[x, y][:3] == (255, 255, 255)
               for x in range(img.width) for y in range(img.height) if pixels[x, y][3] > 0)
    assert img.getpixel((0, 0))[3] == 0 and img.getpixel((30, 16))[3] > 0


def test_pills_are_cached_images_not_tk_ovals(cloud):
    kinds = {cloud.type(i) for i in cloud.find_all()}
    assert "oval" not in kinds and "arc" not in kinds and "image" in kinds
    before = len(cloud._images)
    cloud.redraw()
    assert len(cloud._images) == before  # same sizes and colours reuse the images


def test_panel_background_follows_a_theme_switch(root):
    sv_ttk = pytest.importorskip("sv_ttk")
    from tkinter import ttk
    cloud = cc.ChipCloud(root, LABELS, lambda _l: None, panel_background=True)
    cloud.pack(fill="x")
    try:
        seen = set()
        for theme in ("dark", "light", "dark"):
            sv_ttk.set_theme(theme)
            root.update()
            root.update()  # the redraw is queued with after_idle
            panel = str(ttk.Style().lookup("TFrame", "background"))
            assert str(cloud.cget("background")) == panel, theme
            seen.add(panel)
        assert len(seen) == 2  # the two themes really differ, so the check is not vacuous
    finally:
        cloud.destroy()
        sv_ttk.set_theme("light")
