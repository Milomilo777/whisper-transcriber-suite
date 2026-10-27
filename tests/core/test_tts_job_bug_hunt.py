"""Bug-hunt tests for core/tts_job.py, core/tts_plan.py and core/tts_kokoro.py:
edge cases of text splitting, job identity, plan building, reference-clip
keeping, output naming and chunk timing (fakes only, no engine, no Tk)."""
from __future__ import annotations

import wave
from pathlib import Path

import pytest

from core import synthetic_audio, tts_job


RATE = 1000


def _write_wav(path: str, seconds: float, value: int = 1) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with wave.open(path, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(value.to_bytes(2, "little", signed=True) * int(seconds * RATE))


def test_kept_clips_are_found_before_the_first_piece_is_done(tmp_path):
    """A clone job cancelled (or killed) after it copied its reference clips
    but before its first piece finished has no progress.json and no
    finished.json yet: the copies are the only trace of its voice, and
    find_kept_references is how the tab offers them back on the next run."""
    text = " ".join(f"Sentence number {i} is here." for i in range(1, 21))
    clip_a, clip_b = tmp_path / "a.wav", tmp_path / "b.wav"
    _write_wav(str(clip_a), 0.5, value=10)
    _write_wav(str(clip_b), 0.5, value=20)
    identity = {"mode": "clone", "language": "en",
                "references": [synthetic_audio.sha256_file(clip_a),
                               synthetic_audio.sha256_file(clip_b)]}
    job = tts_job.open_job("omnivoice", text, identity, 1.0, root=tmp_path)
    kept = job.keep_references([str(clip_a), str(clip_b)])
    assert [Path(p).name for p in kept] == ["ref-1.wav", "ref-2.wav"]

    found = tts_job.find_kept_references(
        "omnivoice", text, {"mode": "clone", "language": "en"}, 1.0, root=tmp_path)

    assert found is not None, "a job that only kept its clips was skipped"
    clips, finished = found
    assert finished is False
    assert [Path(p).name for p in clips] == ["ref-1.wav", "ref-2.wav"]
    assert [Path(p).read_bytes() for p in clips] == [clip_a.read_bytes(),
                                                     clip_b.read_bytes()]
