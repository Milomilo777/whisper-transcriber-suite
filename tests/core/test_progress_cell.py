"""Tests for the progress-bar cell renderer in ``app.widgets.tabs``.

``progress_cell`` draws the per-row progress in the queue Treeviews as a
fixed-width block bar plus the exact percentage, so the user sees a
graphical trend and the number in one column.
"""
from __future__ import annotations

from app.widgets.tabs import marquee_cell, progress_cell, progress_column_width


def _bar(cell: str) -> str:
    # The block bar is always the first 10 cells; the rest is " NNN%".
    return cell[:10]


def test_progress_cell_zero():
    cell = progress_cell(0)
    assert _bar(cell) == "░" * 10
    assert cell.endswith("  0%")


def test_progress_cell_full():
    cell = progress_cell(100)
    assert _bar(cell) == "█" * 10
    assert cell.endswith("100%")


def test_progress_cell_half():
    cell = progress_cell(50)
    assert _bar(cell) == "█" * 5 + "░" * 5
    assert cell.endswith(" 50%")


def test_progress_cell_rounds_to_nearest_segment():
    assert _bar(progress_cell(42)) == "█" * 4 + "░" * 6   # 4.2 -> 4
    assert _bar(progress_cell(47)) == "█" * 5 + "░" * 5   # 4.7 -> 5


def test_progress_cell_clamps_out_of_range():
    assert _bar(progress_cell(-10)) == "░" * 10
    assert _bar(progress_cell(150)) == "█" * 10
    assert progress_cell(150).endswith("100%")


def test_progress_cell_handles_float_and_bad_input():
    assert progress_cell(33.7).endswith(" 34%")
    assert _bar(progress_cell(None)) == "░" * 10  # type: ignore[arg-type]


def test_progress_cell_has_constant_width():
    # Constant width keeps the column from jittering as the number grows.
    widths = {len(progress_cell(p)) for p in (0, 5, 50, 99, 100)}
    assert widths == {15}


# --- marquee_cell: indeterminate "working" animation ----------------------


def test_marquee_cell_always_three_lit_blocks():
    for frame in range(0, 25):
        assert marquee_cell(frame).count("▓") == 3


def test_marquee_cell_constant_width():
    assert len({len(marquee_cell(f, p) ) for f in range(0, 25) for p in (0, 50, 100)}) == 1


def test_marquee_cell_advances_with_frame():
    # Consecutive frames differ, so the bar visibly moves.
    assert marquee_cell(0) != marquee_cell(1)


def test_marquee_cell_wraps_each_track_length():
    # The lit window has a 10-segment period, so it loops smoothly.
    assert marquee_cell(0) == marquee_cell(10)


def test_marquee_cell_still_shows_the_percentage():
    # "Have both": the moving bar must still carry the number so the user
    # always sees how far along it is (the colleague's regression).
    assert marquee_cell(0, 0).endswith("  0%")
    assert marquee_cell(3, 7).endswith("  7%")
    assert marquee_cell(3, 100).endswith("100%")


# --- progress_column_width: the column fits "100%" ---------------------------


def _wide_blocks(text: str) -> int:
    # Windows 10 draws the block glyphs from a fallback font about 21 px wide.
    return sum(21 if ch in "█░▓" else 8 for ch in text)


def test_progress_column_fits_a_full_cell_in_wide_glyphs():
    # A fixed 150 px column cut "100%" to "10(" (screenshot review, 2026-10-21).
    assert progress_column_width(_wide_blocks) > _wide_blocks(progress_cell(100))


def test_progress_column_keeps_its_old_width_for_narrow_glyphs():
    from app.dpi import px

    assert progress_column_width(lambda text: 5 * len(text)) == px(150)


def test_both_progress_columns_are_fitted():
    import inspect

    from app.widgets import tabs

    for build, tree in ((tabs.build_queue_tab, "app.tree"), (tabs.build_download_tab, "app.download_tree")):
        src = inspect.getsource(build)
        assert f"fit_progress_column({tree})" in src
        assert '"progress", width=' not in src


def test_progress_column_fits_shade_glyphs_wider_than_the_block():
    # A fallback font need not draw the shade glyphs as wide as the full block (review 2026-10-21).
    def measure(text: str) -> int:
        return sum(30 if ch in "░▓" else 12 if ch == "█" else 8 for ch in text)

    assert progress_column_width(measure) > measure(progress_cell(0))
