"""The status bar's short line for engine log messages (click-through test 2026-10-21)."""
from __future__ import annotations

import pytest

from app.domain.status_line import MAX_CHARS, status_line


@pytest.mark.parametrize("message", [
    "[file=audio.flac] Loop guard: kept 6 identical lines '妈妈的' (avg_logprob=-0.44, "
    "compression_ratio=2.28, no_speech_prob=0.01)",
    "[file=audio.flac] Resume: transcribing tail slice C:\\Users\\x\\partials\\abc.slice.wav",
    "model_path_resolved path=C:\\models\\x source=hub",
    "",
    "   ",
])
def test_diagnostics_keep_the_current_status(message):
    assert status_line(message) is None


def test_a_segment_line_becomes_progress_and_text():
    line = status_line("[file=audio.flac] [12%] 00:01:37 --> 00:01:38 | 我给你")
    assert line == "audio.flac: 12% done — “我给你”"  # quoted: they are the recording's words


def test_a_segment_without_text_or_file_name():
    assert status_line("[ 5%] 00:00:00 --> 00:00:03 | ") == "5% done"


def test_processing_shows_the_file_name_not_the_path():
    assert status_line("[file=audio.flac] Processing: C:/Users/Owner/mixfull/audio.flac") == "Transcribing audio.flac…"
    assert status_line("Processing (nvidia_asr): D:/calls/call 1.m4a") == "Transcribing call 1.m4a…"


def test_other_messages_pass_with_the_file_name():
    assert status_line("Model loaded") == "Model loaded"
    assert status_line("[file=a.mp3] Detected 1 chapter(s) in the transcript.") == \
        "a.mp3: Detected 1 chapter(s) in the transcript."
    assert status_line("sample_clip.srt has no audio track, so there is nothing to transcribe.") == \
        "sample_clip.srt has no audio track, so there is nothing to transcribe."


def test_long_lines_are_cut_to_fit_the_bar():
    long_text = "word " * 100
    for message in (f"[file=x.mp3] [50%] 00:00:00 --> 00:00:09 | {long_text}", long_text,
                    "سلام " * 60):
        line = status_line(message)
        assert line is not None and len(line) <= MAX_CHARS and line.endswith("…")
