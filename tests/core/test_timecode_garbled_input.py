"""Garbled numeric input must be rejected by _parse_timecode.

The docstring promises ``None`` for "any string the parser can't make
sense of". Python's ``float()`` silently accepts digit-group separators
(``"1_000"`` -> 1000.0) and sign prefixes, so a garbled Start/End value
slipped through and produced a wrong ``--download-sections`` range.
"""
from __future__ import annotations

from app.services.download_service import _parse_timecode


def test_parse_timecode_rejects_underscore_digits() -> None:
    assert _parse_timecode("1_000") is None
    assert _parse_timecode("9_0") is None
    assert _parse_timecode("1:2_0") is None


def test_parse_timecode_rejects_explicit_sign() -> None:
    assert _parse_timecode("+90") is None
    assert _parse_timecode("1:+30") is None
