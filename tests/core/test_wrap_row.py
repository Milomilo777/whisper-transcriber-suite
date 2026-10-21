"""app.widgets.wrap_row.flow_rows (the line-break rule, no Tk) and tabs.download_range_is_set."""
from __future__ import annotations

import pytest

from app.widgets.wrap_row import flow_rows


def test_everything_fits_on_one_line() -> None:
    assert flow_rows([100, 100, 100], 10, 320) == [[0, 1, 2]]
    assert flow_rows([100, 100, 100], 10, 10_000) == [[0, 1, 2]]


def test_a_gap_counts_toward_the_width() -> None:
    assert flow_rows([100, 100, 100], 10, 319) == [[0, 1], [2]]


def test_cells_flow_greedily_onto_as_many_lines_as_needed() -> None:
    assert flow_rows([300, 300, 300], 18, 400) == [[0], [1], [2]]
    assert flow_rows([200, 150, 200, 150], 10, 400) == [[0, 1], [2, 3]]


def test_a_cell_wider_than_the_line_still_gets_a_line() -> None:
    assert flow_rows([900, 50], 10, 400) == [[0], [1]]
    assert flow_rows([50, 900], 10, 400) == [[0], [1]]


def test_no_width_yet_keeps_one_line() -> None:
    # Before Tk lays the row out winfo_width() is 0 or 1: never wrap on that.
    assert flow_rows([300, 300, 300], 18, 0) == [[0, 1, 2]]
    assert flow_rows([300, 300, 300], 18, 1) == [[0, 1, 2]]
    assert flow_rows([300, 300, 300], 18, 2) == [[0], [1], [2]]
    assert flow_rows([], 18, 500) == [[]]


def test_popdown_extra_px_is_the_shortfall_or_zero() -> None:
    from app.widgets.tabs import popdown_extra_px

    assert popdown_extra_px(400, 167) == 233
    assert popdown_extra_px(167, 167) == 0
    assert popdown_extra_px(100, 167) == 0


@pytest.mark.parametrize(
    "start, end, expected",
    [
        ("0:00:00", "0:00:00", False),
        ("", "", False),
        ("0:00", "", False),
        ("garbage", "0:00:00", False),  # read as unset by the download service
        ("0:00:30", "0:00:00", True),
        ("0:00:00", "1:25", True),
        ("0:00:00", "  90 ", True),
    ],
)
def test_download_range_is_set(start: str, end: str, expected: bool) -> None:
    from app.widgets.tabs import download_range_is_set

    assert download_range_is_set(start, end) is expected
