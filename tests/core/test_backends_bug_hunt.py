"""Bug-hunt tests for core/backends/ (non-GPU logic, fakes only).

Each test pins a defect found in the starting commit: it fails before the
matching fix and passes after. Engines are always faked — no model is
loaded, no network is touched.
"""
from __future__ import annotations

import math
import sys
import types

import pytest


@pytest.fixture
def cs():
    """core.backends.cloud_stt with faster_whisper stubbed (import guard)."""
    if "faster_whisper" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fake_fw
    from core.backends import cloud_stt as mod
    return mod


@pytest.fixture
def gcs():
    """core.backends.google_cloud_stt (no google libs at import time)."""
    if "faster_whisper" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fake_fw
    from core.backends import google_cloud_stt as mod
    return mod


# ---------------------------------------------------------------- bug 1


def test_parse_transcript_skips_timestamp_line_with_no_text(cs):
    """An empty utterance line "[ts --> ts]" (no text after the bracket) must
    not produce a junk segment: the parser's text group used to swallow the
    closing bracket, yielding a subtitle cue whose whole text is "]".
    """
    text = (
        "[00:00:01.000 --> 00:00:02.000] hello there\n"
        "[00:00:03.000 --> 00:00:04.000]\n"
        "[00:00:05.000 --> 00:00:06.000] next line\n"
    )
    segs = cs.parse_transcript_to_segments(text)
    assert [s["text"] for s in segs] == ["hello there", "next line"]
    assert segs[1]["start"] == 5.0
    assert segs[1]["end"] == 6.0


def test_parse_transcript_empty_utterance_first_line_yields_no_junk(cs):
    """A bare timestamp line as the FIRST line must not seed a "]" segment
    nor poison the following continuation logic."""
    text = "[00:00:00.500 --> 00:00:01.000]\n[00:00:01.000 --> 00:00:02.000] real text\n"
    segs = cs.parse_transcript_to_segments(text)
    assert segs == [{"start": 1.0, "end": 2.0, "text": "real text"}]


# ---------------------------------------------------------------- bug 2


def test_plan_chunks_nan_window_falls_back_to_default(cs):
    """A non-finite chunk length (hand-edited config, e.g. "nan") must hit
    the same fallback as a zero/negative one. NaN evades the ``<= 0`` guard,
    producing (0.0, nan) windows that reach ffmpeg as ``-t nan``."""
    windows = cs.plan_chunks(960.0, float("nan"))
    assert windows == [(0.0, 480.0), (480.0, 960.0)]


def test_plan_chunks_nan_window_unknown_duration_falls_back(cs):
    windows = cs.plan_chunks(0.0, float("nan"), chunk_when_unknown=True)
    assert all(math.isfinite(s) and math.isfinite(e) for s, e in windows)
    assert windows[0] == (0.0, 480.0)


def test_gcs_plan_chunks_nan_window_falls_back_to_default(gcs):
    """Same guard in google_cloud_stt.plan_chunks (own copy of the logic)."""
    windows = gcs.plan_chunks(110.0, float("nan"))
    assert windows == [(0.0, 55.0), (55.0, 110.0)]


# ---------------------------------------------------------------- bug 3


def test_gcs_unknown_plan_coverage_does_not_shrink_with_small_windows(gcs):
    """A smaller configured chunk_seconds (e.g. 5 s to stay under the inline
    byte cap) must not shrink the unknown-duration plan's COVERAGE: the
    fixed 1200-window cap silently truncated any file longer than
    1200 * 5 s = 100 min whenever ffprobe could not read its duration
    (progress still reached 100%). Same defect class nvidia_asr's
    UNKNOWN_PLAN_COVERAGE_SECONDS comment documents."""
    windows = gcs.plan_chunks(0.0, 5.0)
    expected_coverage = (
        gcs.MAX_UNKNOWN_DURATION_CHUNKS * gcs.DEFAULT_CHUNK_SECONDS
    )
    assert windows[-1][1] >= expected_coverage - 5.0


def test_cloud_unknown_plan_coverage_does_not_shrink_with_small_windows(cs):
    """cloud_stt's own caller (transcribe_to_segments) never passes
    max_unknown_chunks, so its documented trap applies to itself: with
    cloud_stt_chunk_seconds=60 the unknown-length plan covered only
    120 * 60 s = 2 h instead of the default 16 h."""
    windows = cs.plan_chunks(0.0, 60.0, chunk_when_unknown=True)
    expected_coverage = cs.MAX_UNKNOWN_DURATION_CHUNKS * 480.0
    assert windows[-1][1] >= expected_coverage - 60.0
