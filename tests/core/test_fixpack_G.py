"""Regression tests for fixpack cluster G (core/writers).

Covers two confirmed bugs:

  1. ``fmt_lrc_time`` emitted an illegal ``:60.00`` seconds field for
     start times microseconds below a whole-minute boundary, because it
     rounded the float remainder *after* the divmod.
  2. The TSV writer raised ValueError/OverflowError on NaN/Inf
     timestamps where every peer writer clamps them to a safe default.
"""
from __future__ import annotations

import math

import pytest

from core.writers import lrc, tsv
from core.writers.base import fmt_lrc_time


# --- Bug 1: fmt_lrc_time must never emit ":60.00" -------------------------


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (0.0, "[00:00.00]"),
        (75.5, "[01:15.50]"),          # existing documented behaviour
        (59.996, "[01:00.00]"),        # rounds up into the next minute
        (59.999, "[01:00.00]"),
        (119.996, "[02:00.00]"),
        (179.999, "[03:00.00]"),
        (59.994, "[00:59.99]"),        # just below the carry threshold
        (3599.996, "[60:00.00]"),      # an hour rolls into mm=60 (LRC has no HH)
    ],
)
def test_fmt_lrc_time_never_emits_sixty_seconds(seconds, expected):
    assert fmt_lrc_time(seconds) == expected


def test_fmt_lrc_time_seconds_field_always_in_range():
    """Sweep the whole near-minute window that used to overflow to 60."""
    for milli in range(59_990, 60_000):  # 59.990 .. 59.999
        out = fmt_lrc_time(milli / 1000.0)
        body = out.strip("[]")
        mm, ss = body.split(":")
        sec = float(ss)
        assert 0.0 <= sec < 60.0, f"{out} has illegal seconds field"


def test_fmt_lrc_time_clamps_nonfinite_and_negative():
    assert fmt_lrc_time(float("nan")) == "[00:00.00]"
    assert fmt_lrc_time(float("inf")) == "[00:00.00]"
    assert fmt_lrc_time(-5.0) == "[00:00.00]"


def test_lrc_writer_does_not_emit_sixty_in_cue():
    """End-to-end through the LRC writer: a near-minute start must roll
    over rather than produce a parser-rejecting ``[mm:60.00]`` cue."""
    body = lrc.write([{"start": 59.999, "end": 61.0, "text": "edge"}])
    assert ":60.00" not in body
    assert "[01:00.00]edge" in body


# --- Bug 2: TSV writer clamps NaN/Inf instead of raising ------------------


def test_tsv_writer_clamps_nan_timestamp():
    body = tsv.write([{"start": float("nan"), "end": 1.0, "text": "hi"}])
    line = body.strip().split("\n")[1]
    start_ms, end_ms, text = line.split("\t")
    assert start_ms == "0"
    assert end_ms == "1000"
    assert text == "hi"


def test_tsv_writer_clamps_inf_timestamp():
    body = tsv.write([{"start": 0.5, "end": float("inf"), "text": "hi"}])
    line = body.strip().split("\n")[1]
    start_ms, end_ms, _ = line.split("\t")
    assert start_ms == "500"
    # Clamped to the start like the subtitle writers (0 made a
    # negative-length row).
    assert end_ms == "500"


def test_tsv_writer_clamps_negative_timestamp():
    body = tsv.write([{"start": -2.0, "end": 1.0, "text": "hi"}])
    line = body.strip().split("\n")[1]
    start_ms = line.split("\t")[0]
    assert start_ms == "0"


def test_tsv_writer_does_not_raise_on_nan_inf():
    # The whole point: a single non-finite segment must not abort the
    # write and silently drop the .tsv output.
    segs = [
        {"start": float("nan"), "end": float("inf"), "text": "bad"},
        {"start": 1.0, "end": 2.0, "text": "good"},
    ]
    body = tsv.write(segs)  # must not raise
    assert "good" in body
    assert body.startswith("start\tend\ttext\n")
    # Both data rows survive.
    assert len(body.strip().split("\n")) == 3


def test_tsv_writer_tolerates_missing_start_key():
    # Peer writers (txt/srt/json/docx) use .get with a default; TSV now
    # matches them rather than KeyError-ing on a hand-edited segment.
    body = tsv.write([{"end": 1.0, "text": "hi"}])  # no "start"
    line = body.strip().split("\n")[1]
    assert line.split("\t")[0] == "0"


def test_tsv_writer_normal_values_unchanged():
    body = tsv.write([{"start": 0.0, "end": 1.5, "text": "Hello"}])
    line = body.strip().split("\n")[1]
    assert line == "0\t1500\tHello"


def test_ms_helper_is_finite_safe():
    # Direct unit check of the clamp helper.
    assert tsv._ms(float("nan")) == 0
    assert tsv._ms(float("inf")) == 0
    assert tsv._ms(-1.0) == 0
    assert tsv._ms(1.5) == 1500
    assert tsv._ms(None) == 0
    assert math.isfinite(float(tsv._ms(2.0)))
