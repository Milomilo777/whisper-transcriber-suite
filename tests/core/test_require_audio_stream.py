"""require_audio_stream: a video-only file gets a readable error.

Without it, faster-whisper's PyAV decode fails with a bare
"tuple index out of range" (seen with a real 3 s testsrc MP4).
"""
from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest

from core import transcriber


def _fake_run(stdout: str, returncode: int = 0):
    def run(*_a, **_k):
        return SimpleNamespace(stdout=stdout, stderr="", returncode=returncode)
    return run


def test_no_audio_stream_raises_readable_error(monkeypatch):
    monkeypatch.setattr(transcriber.subprocess, "run", _fake_run(""))
    with pytest.raises(RuntimeError, match="no audio track"):
        transcriber.require_audio_stream("C:/clips/screen.mp4")


def test_audio_stream_present_passes(monkeypatch):
    monkeypatch.setattr(transcriber.subprocess, "run", _fake_run("1\n"))
    transcriber.require_audio_stream("C:/clips/talk.mp4")


def test_ffprobe_failure_is_left_to_the_decoder(monkeypatch):
    monkeypatch.setattr(transcriber.subprocess, "run", _fake_run("", returncode=1))
    transcriber.require_audio_stream("C:/clips/odd.bin")

    def boom(*_a, **_k):
        raise subprocess.TimeoutExpired("ffprobe", 60)

    monkeypatch.setattr(transcriber.subprocess, "run", boom)
    transcriber.require_audio_stream("C:/clips/slow.mp4")
