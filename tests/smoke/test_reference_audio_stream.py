"""A duration-bearing video with no audio is not a usable voice reference."""
import os
from pathlib import Path
import shutil
import subprocess
import wave

import pytest


@pytest.fixture
def native_audio_probe(monkeypatch):
    ffmpeg = os.environ.get("WHISPER_SMOKE_FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).is_file():
        pytest.skip("Native FFmpeg is required")
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    ffprobe = os.environ.get("WHISPER_SMOKE_FFPROBE") or (
        str(sibling) if sibling.is_file() else shutil.which("ffprobe")
    )
    if not ffprobe or not Path(ffprobe).is_file():
        pytest.skip("Native FFprobe is required")
    from core import transcriber

    original = transcriber.bundled_binary
    monkeypatch.setattr(transcriber, "bundled_binary", lambda name: ffprobe if name == "ffprobe" else original(name))
    return ffmpeg


@pytest.mark.parametrize("suffix", [".mp4", ".wav"])
def test_video_without_audio_is_a_blocking_reference_issue(native_audio_probe, tmp_path, suffix):
    from core import transcriber, voice_clone

    source = tmp_path / ("silent-video" + suffix)
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    result = subprocess.run(
        [native_audio_probe, "-nostdin", "-y", "-v", "error", "-f", "lavfi", "-i",
         "color=c=black:s=32x32:r=2:d=4", "-an", "-c:v", "mpeg4", "-f", "mp4", str(source)],
        capture_output=True, timeout=20, **kwargs,
    )
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
    original = source.read_bytes()
    assert 3 <= transcriber.get_duration(str(source)) <= 10
    with pytest.raises(RuntimeError, match="no audio track"):
        transcriber.require_audio_stream(str(source))
    issue = voice_clone.validate_reference_sample(str(source))
    assert source.read_bytes() == original
    assert issue is not None and issue.blocking


def test_real_audio_reference_remains_usable(native_audio_probe, tmp_path):
    from core import transcriber, voice_clone

    source = tmp_path / "reference.wav"
    with wave.open(str(source), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * (4 * 16000))
    original = source.read_bytes()
    transcriber.require_audio_stream(str(source))
    assert voice_clone.validate_reference_sample(str(source)) is None
    assert source.read_bytes() == original
