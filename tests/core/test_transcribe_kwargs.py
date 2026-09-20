"""Tests for _build_transcribe_kwargs language handling.

This is the central kwargs builder for the DEFAULT faster-whisper path, so
it must coerce any UI/download language hint into a code faster-whisper
accepts — otherwise a region tag ("en-US") or a multi-value picker code
("zh-Hans,zh-CN") raises ValueError and produces no output.
"""
from __future__ import annotations

from core.task import TranscriptionTask
from core.transcriber import _build_transcribe_kwargs, _clip_timestamps_arg


def _task(language) -> TranscriptionTask:
    t = TranscriptionTask("clip.mp4")
    t.language = language
    return t


def _clip_task(start, end) -> TranscriptionTask:
    t = TranscriptionTask("clip.mp4")
    t.clip_start = start
    t.clip_end = end
    return t


def test_region_tag_reduced_to_base():
    assert _build_transcribe_kwargs(_task("en-US")).get("language") == "en"


def test_multivalue_picker_code_reduced_to_base():
    assert _build_transcribe_kwargs(_task("zh-Hans,zh-CN")).get("language") == "zh"
    assert _build_transcribe_kwargs(_task("pt,pt-BR,pt-PT")).get("language") == "pt"


def test_plain_code_passes_through():
    assert _build_transcribe_kwargs(_task("fa")).get("language") == "fa"


def test_picker_hebrew_code_reaches_whisper_as_he():
    # The Transcribe tab maps the "Hebrew" picker entry to "iw" (the UI's
    # yt-dlp-aligned table); faster-whisper only accepts "he", so the
    # kwargs builder must translate rather than silently auto-detect.
    assert _build_transcribe_kwargs(_task("iw")).get("language") == "he"


def test_language_omitted_when_unset_or_auto():
    # None / "Auto" / unknown all mean auto-detect: no language kwarg at all.
    assert "language" not in _build_transcribe_kwargs(_task(None))
    assert "language" not in _build_transcribe_kwargs(_task("Auto"))
    assert "language" not in _build_transcribe_kwargs(_task("klingon"))


# --- clip_timestamps (Transcribe-tab time-slice) --------------------------


def test_clip_timestamps_both_bounds():
    assert _clip_timestamps_arg(_clip_task(30, 90)) == "30.0,90.0"


def test_clip_timestamps_start_only_open_end():
    assert _clip_timestamps_arg(_clip_task(30, None)) == "30.0"
    assert _clip_timestamps_arg(_clip_task(30, 0)) == "30.0"


def test_clip_timestamps_end_only():
    assert _clip_timestamps_arg(_clip_task(0, 90)) == "0.0,90.0"


def test_clip_timestamps_none_when_unset():
    assert _clip_timestamps_arg(_clip_task(None, None)) is None
    assert _clip_timestamps_arg(_clip_task(0, 0)) is None


def test_clip_timestamps_end_le_start_is_open_ended():
    # A nonsensical end <= start degrades to "from start to end of file".
    assert _clip_timestamps_arg(_clip_task(90, 30)) == "90.0"
