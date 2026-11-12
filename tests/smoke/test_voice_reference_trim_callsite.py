"""The real reference-loader trim path produces WAV for compressed inputs."""
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import wave

import pytest


@pytest.fixture
def native_tools(monkeypatch):
    ffmpeg = os.environ.get("WHISPER_SMOKE_FFMPEG") or shutil.which("ffmpeg")
    if not ffmpeg or not Path(ffmpeg).is_file():
        pytest.skip("Native FFmpeg is required")
    sibling = Path(ffmpeg).with_name("ffprobe.exe" if os.name == "nt" else "ffprobe")
    ffprobe = os.environ.get("WHISPER_SMOKE_FFPROBE") or (
        str(sibling) if sibling.is_file() else shutil.which("ffprobe")
    )
    if not ffprobe or not Path(ffprobe).is_file():
        pytest.skip("Native FFprobe is required")
    from core import paths, transcriber

    binary = paths.bundled_binary
    probe_binary = transcriber.bundled_binary
    monkeypatch.setattr(paths, "bundled_binary", lambda name: ffmpeg if name == "ffmpeg" else binary(name))
    monkeypatch.setattr(transcriber, "bundled_binary", lambda name: ffprobe if name == "ffprobe" else probe_binary(name))
    return ffmpeg


@pytest.mark.parametrize("suffix,codec", [
    (".wav", None), (".mp3", "libmp3lame"), (".m4a", "aac"),
    (".ogg", "libvorbis"), (".flac", "flac"),
])
def test_reference_loader_trims_compressed_sources_to_valid_wav(
    native_tools, monkeypatch, tmp_path, suffix, codec,
):
    from app.widgets import voice_clone_tab as tab
    from core import _threads, voice_clone

    original_wav = tmp_path / "source.wav"
    with wave.open(str(original_wav), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * (12 * 16000))
    source = original_wav
    if codec is not None:
        source = tmp_path / ("reference \u0622\u0632\u0645\u0627\u06cc\u0634" + suffix)
        kwargs = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        conversion = subprocess.run(
            [native_tools, "-nostdin", "-y", "-v", "error", "-i", str(original_wav),
             "-c:a", codec, str(source)], capture_output=True, timeout=20, **kwargs,
        )
        assert conversion.returncode == 0, conversion.stderr.decode("utf-8", errors="replace")
    original = source.read_bytes()
    scratch = tmp_path / "trimmed"
    scratch.mkdir()
    monkeypatch.setattr(voice_clone, "session_work_dir", lambda: str(scratch))
    monkeypatch.setattr(_threads, "safe_thread", lambda function, **kwargs: function())
    accepted = []
    monkeypatch.setattr(tab, "_finish_adding_sample", lambda app, path, issue: accepted.append((path, issue)))
    app = SimpleNamespace(vc_samples=[], post_to_main=lambda callback: callback())
    tab._validate_and_add_sample(app, str(source))
    assert len(accepted) == 1
    path, issue = accepted[0]
    assert issue is None
    trimmed = Path(path)
    assert trimmed != source and trimmed.suffix.lower() == ".wav"
    with wave.open(str(trimmed), "rb") as audio:
        assert audio.getcomptype() == "NONE"
        assert 0 < audio.getnframes() <= audio.getframerate() * voice_clone.MAX_REFERENCE_SECONDS
    assert voice_clone.validate_reference_sample(str(trimmed)) is None
    assert source.read_bytes() == original
