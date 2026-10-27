"""A present-but-broken numpy must degrade to the stdlib paths, not raise.

numpy is optional for the live engine: ``block_rms`` and ``RateConverter``
both document a pure-stdlib fallback, and ``recorder._downmix_to_mono_int16``
already treats a numpy that raises OSError at import (the classic missing
MKL/DLL failure) as "no numpy". The live engine caught only ImportError,
so a broken numpy made every captured block raise inside ``_on_frames`` —
and because the recorder swallows sink exceptions, the session silently
transcribed nothing while looking perfectly healthy.
"""
from __future__ import annotations

import array
import builtins
import math

import pytest

from core import live


def _break_numpy(monkeypatch):
    """Make ``import numpy`` raise OSError, like a broken native install."""
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "numpy":
            raise OSError("DLL load failed while importing numpy")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)


def _tone(seconds: float, rate: int = 16_000, amp: int = 8000,
          freq: float = 220.0) -> bytes:
    out = array.array("h")
    for i in range(int(rate * seconds)):
        out.append(int(amp * math.sin(2 * math.pi * freq * i / rate)))
    return out.tobytes()


def test_block_rms_survives_a_broken_numpy(monkeypatch):
    with_np = live.block_rms(_tone(0.1))
    assert with_np > 0.1  # a 8000-amplitude sine is ~0.17 normalised RMS
    _break_numpy(monkeypatch)
    pure = live.block_rms(_tone(0.1))
    # Same tone on the stdlib path: the documented numpy-free fallback.
    assert pure == pytest.approx(with_np, rel=0.05)


def test_rate_converter_survives_a_broken_numpy(monkeypatch):
    _break_numpy(monkeypatch)
    src = _tone(0.5, rate=48_000)
    conv = live.RateConverter(48_000, 16_000)
    out = b"".join(conv.convert(src[i:i + 1000]) for i in range(0, len(src), 1000))
    samples = array.array("h")
    samples.frombytes(out)
    # 0.5 s at 16 kHz, give or take the interpolator's 2-sample latency.
    assert abs(len(samples) - 0.5 * 16_000) <= 4


def test_session_still_chunks_audio_when_numpy_is_broken(monkeypatch, tmp_path):
    """End to end: a broken numpy must not silently stop transcription."""
    _break_numpy(monkeypatch)
    session = live.LiveSession(
        transcribe_chunk=lambda p: "hello", work_dir=str(tmp_path / "work")
    )
    pcm = _tone(3.0) + b"\x00\x00" * int(16_000 * 0.8)
    for i in range(0, len(pcm), 2048):
        session._on_frames(pcm[i:i + 2048], 16_000)
    assert not session._chunks.empty()
