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


def test_collapsed_shows_one_row_ending_in_more_and_expands_to_all(cloud, root):
    chips = cloud._chips
    assert chips[-1].toggle and chips[-1].text.startswith("+")
    hidden = int(chips[-1].text[1:].split()[0])
    assert len(chips) - 1 + hidden == len(LABELS)
    assert len({c.y for c in chips}) == 1  # one row
    cloud.activate(len(chips) - 1)
    root.update()
    labels = [c.label for c in cloud._chips if not c.toggle]
    assert labels == LABELS and cloud._chips[-1].text == "Show less"
    cloud.activate(len(cloud._chips) - 1)
    assert not cloud.expanded


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
    assert _contrast(pal["toggle_fg"], pal["normal_bg"]) >= 4.5, theme


def test_pills_are_cached_images_not_tk_ovals(cloud):
    kinds = {cloud.type(i) for i in cloud.find_all()}
    assert "oval" not in kinds and "arc" not in kinds and "image" in kinds
    before = len(cloud._images)
    cloud.redraw()
    assert len(cloud._images) == before  # same sizes and colours reuse the images
