"""Native FFmpeg checks of reference trimming; no TTS model is loaded."""
import os
from pathlib import Path
import shutil
import subprocess
import wave

import pytest


@pytest.fixture
def native_trim(monkeypatch):
    executable = os.environ.get("WHISPER_SMOKE_FFMPEG") or shutil.which("ffmpeg")
    if not executable or not Path(executable).is_file():
        pytest.skip("Native FFmpeg is required")
    from core import paths, voice_clone

    original = paths.bundled_binary
    monkeypatch.setattr(paths, "bundled_binary", lambda name: executable if name == "ffmpeg" else original(name))
    return voice_clone


def make_reference(path):
    with wave.open(str(path), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * (12 * 16000))


@pytest.mark.parametrize("seconds", [3.0, 10.0])
def test_native_trim_does_not_exceed_requested_length(native_trim, tmp_path, seconds):
    source = tmp_path / "reference.wav"
    output = tmp_path / "trimmed.wav"
    make_reference(source)
    original = source.read_bytes()
    native_trim.trim_reference_sample(str(source), str(output), max_seconds=seconds)
    with wave.open(str(output)) as audio:
        assert audio.getnframes() > 0
        assert audio.getnframes() <= int(seconds * audio.getframerate())
    assert source.read_bytes() == original


def test_native_trim_failure_preserves_existing_output(native_trim, tmp_path):
    source = tmp_path / "not-audio.wav"
    source.write_bytes(b"synthetic invalid input")
    output = tmp_path / "previous.wav"
    make_reference(output)
    previous = output.read_bytes()
    with pytest.raises(RuntimeError, match="Could not trim"):
        native_trim.trim_reference_sample(str(source), str(output))
    assert output.read_bytes() == previous


def test_default_trim_passes_its_own_reference_length_check(native_trim, tmp_path):
    source = tmp_path / "reference.wav"
    output = tmp_path / "trimmed.wav"
    make_reference(source)
    native_trim.trim_reference_sample(str(source), str(output))
    assert native_trim.validate_reference_sample(str(output)) is None


@pytest.mark.parametrize("extension,encoder", [
    ("mp3", "libmp3lame"), ("m4a", "aac"), ("ogg", "libvorbis"),
    ("flac", "flac"), ("wav", "pcm_s24le"),
])
@pytest.mark.parametrize("seconds", [3.0, 10.0])
def test_trim_decodes_supported_inputs_to_bounded_pcm(
    native_trim, tmp_path, extension, encoder, seconds,
):
    from core.paths import bundled_binary

    source = tmp_path / ("reference_\u6e2c\u8a66." + extension)
    subprocess.run([
        bundled_binary("ffmpeg"), "-y", "-v", "error", "-f", "lavfi", "-i",
        "sine=frequency=440:duration=12:sample_rate=44100", "-ac", "2",
        "-c:a", encoder, str(source),
    ], check=True, capture_output=True, timeout=30)
    original = source.read_bytes()
    output = tmp_path / "trimmed.wav"
    native_trim.trim_reference_sample(str(source), str(output), max_seconds=seconds)
    with wave.open(str(output)) as audio:
        assert audio.getsampwidth() == 2
        assert audio.getframerate() == 44100
        assert audio.getnchannels() == 2
        assert 0 < audio.getnframes() <= int(seconds * audio.getframerate())
    assert source.read_bytes() == original
