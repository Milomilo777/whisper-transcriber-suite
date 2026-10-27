"""app.widgets.tabs._fmt_bytes at the unit rounding boundaries.

A file one byte under a megabyte is 1023.999 KiB; ``:.1f`` rounds that to
"1024.0 KB", a figure in a unit the function's own threshold replaces with
the MB branch one byte later (same for MB -> GB).
"""
from __future__ import annotations

from app.widgets.tabs import _fmt_bytes

K = 1024


def test_a_file_just_under_a_megabyte_is_not_1024_kb() -> None:
    assert _fmt_bytes(K * K - 1) == "1.0 MB"
    assert _fmt_bytes(K * K - 51) == "1.0 MB"
    assert _fmt_bytes(K * K * K - 1) == "1.00 GB"


def test_sizes_that_round_below_the_next_unit_keep_their_unit() -> None:
    assert _fmt_bytes(K * K - 52) == "1023.9 KB"
    assert _fmt_bytes(1536) == "1.5 KB"
    assert _fmt_bytes(512) == "512 B"
    assert _fmt_bytes(5 * 1024 * 1024) == "5.0 MB"
    assert _fmt_bytes(1.5 * 1024 * 1024 * 1024) == "1.50 GB"
