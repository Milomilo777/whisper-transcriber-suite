"""Property tests (Hypothesis) of app.i18n.embed_rtl and plain(): see tests/test_i18n_rtl.py."""
from __future__ import annotations

import unicodedata

import pytest

from app import i18n

hypothesis = pytest.importorskip("hypothesis")
from hypothesis import given  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

RLE = chr(0x202B)
PDF = chr(0x202C)
ISOLATES = {chr(c) for c in range(0x2066, 0x206A)}
RLM, LRM = chr(0x200F), chr(0x200E)

PIECES = list("ab Z09.:()،؟«»-\n\r\t ") + ["ذ", "خیره", "ש", "۳", chr(0x200C), RLM, LRM]
TEXTS = st.lists(st.sampled_from(PIECES), max_size=30).map("".join)


def _depth_ok(line: str) -> bool:
    depth = 0
    for ch in line:
        if ch == RLE:
            depth += 1
        elif ch == PDF:
            depth -= 1
            if depth < 0:
                return False
        elif unicodedata.bidirectional(ch) in ("R", "AL") and depth == 0:
            return False
    return depth == 0


@given(TEXTS)
def test_property_round_trip_idempotence_and_coverage(text: str) -> None:
    out = i18n.embed_rtl(text)
    assert i18n.plain(out) == text  # nothing lost, nothing reordered
    assert i18n.embed_rtl(out) == out  # idempotent
    assert out.count("\n") == text.count("\n")
    assert not (ISOLATES & set(out))
    for line in out.split("\n"):
        assert _depth_ok(line), repr(line)  # every right-to-left letter inside a pair
        if not any(unicodedata.bidirectional(c) in ("R", "AL") for c in line):
            assert RLE not in line and PDF not in line
    assert out.strip() == i18n.embed_rtl(text.strip())


@given(TEXTS, TEXTS, TEXTS)
def test_property_filled_placeholders_keep_every_letter_inside_a_pair(a: str, b: str, c: str) -> None:
    line = (i18n.embed_rtl(a) + b + i18n.embed_rtl(c)).replace("\n", " ").replace("\r", " ")
    out = i18n.embed_rtl(line)
    assert _depth_ok(out), repr(out)
    assert i18n.plain(out) == i18n.plain(line)
    assert i18n.embed_rtl(out) == out
