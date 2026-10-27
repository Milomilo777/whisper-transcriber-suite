"""Bug-hunt tests for core/backends/ (non-GPU logic, fakes only).

Each test pins a defect found in the starting commit: it fails before the
matching fix and passes after. Engines are always faked — no model is
loaded, no network is touched.
"""
from __future__ import annotations

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
