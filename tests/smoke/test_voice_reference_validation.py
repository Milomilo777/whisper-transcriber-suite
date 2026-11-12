"""Probe real synthetic reference files without downloading or loading TTS models."""
import os
from pathlib import Path
import shutil
import subprocess
import wave

import pytest


@pytest.fixture
def native_reference_tools(monkeypatch):
    ffmpeg = os.environ.get("WHISPER_SMOKE_FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).is_file():
        pytest.skip("Native FFmpeg is required")
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    ffprobe = os.environ.get("WHISPER_SMOKE_FFPROBE") or (
        str(sibling) if sibling.is_file() else shutil.which("ffprobe")
    )
    if not ffprobe or not Path(ffprobe).is_file():
        pytest.skip("Native FFprobe is required")
    from core import transcriber, voice_clone

    original = transcriber.bundled_binary
    monkeypatch.setattr(
        transcriber, "bundled_binary",
        lambda name: ffprobe if name == "ffprobe" else original(name),
    )
    return ffmpeg, voice_clone


def write_reference(path, seconds=6, rate=16000, channels=1, width=2):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((channels, width, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01" * (int(seconds * rate) * channels * width))


@pytest.mark.parametrize("seconds", [1, 3, 6, 10, 12])
def test_real_reference_duration_classification(native_reference_tools, tmp_path, seconds):
    _, engine = native_reference_tools
    source = tmp_path / "reference \u0622\u0632\u0645\u0627\u06cc\u0634.wav"
    write_reference(source, seconds)
    original = source.read_bytes()
    issue = engine.validate_reference_sample(str(source))
    if seconds < engine.MIN_REFERENCE_SECONDS:
        assert issue is not None and not issue.blocking and not issue.too_long
    elif seconds > engine.MAX_REFERENCE_SECONDS:
        assert issue is not None and not issue.blocking and issue.too_long
    else:
        assert issue is None
    assert source.read_bytes() == original


@pytest.mark.parametrize("rate,channels,width", [(48000, 2, 2), (44100, 1, 3), (22050, 1, 1)])
def test_real_reference_pcm_layouts(native_reference_tools, tmp_path, rate, channels, width):
    _, engine = native_reference_tools
    source = tmp_path / "reference.wav"
    write_reference(source, rate=rate, channels=channels, width=width)
    assert engine.validate_reference_sample(str(source)) is None


@pytest.mark.parametrize("kind", ["empty", "text", "header_only"])
def test_real_invalid_reference_is_blocking(native_reference_tools, tmp_path, kind):
    _, engine = native_reference_tools
    source = tmp_path / "unreadable.wav"
    if kind == "header_only":
        write_reference(source, seconds=0)
    else:
        source.write_bytes(b"" if kind == "empty" else b"synthetic invalid audio")
    original = source.read_bytes()
    issue = engine.validate_reference_sample(str(source))
    assert issue is not None and issue.blocking and not issue.too_long
    assert source.read_bytes() == original


@pytest.mark.parametrize("suffix,codec", [
    (".mp3", "libmp3lame"), (".m4a", "aac"), (".ogg", "libvorbis"), (".flac", "flac"),
])
def test_real_compressed_reference_is_usable(native_reference_tools, tmp_path, suffix, codec):
    ffmpeg, engine = native_reference_tools
    source = tmp_path / "source.wav"
    output = tmp_path / ("reference \u0622\u0632\u0645\u0627\u06cc\u0634" + suffix)
    write_reference(source)
    kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    conversion = subprocess.run(
        [ffmpeg, "-nostdin", "-y", "-v", "error", "-i", str(source), "-c:a", codec, str(output)],
        capture_output=True, timeout=20, **kwargs,
    )
    assert conversion.returncode == 0, conversion.stderr.decode("utf-8", errors="replace")
    original = output.read_bytes()
    assert engine.validate_reference_sample(str(output)) is None
    assert output.read_bytes() == original
