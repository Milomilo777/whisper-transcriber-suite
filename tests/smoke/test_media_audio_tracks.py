"""Native FFmpeg tests for source-timeline audio selection."""
import os
import shutil
import subprocess
import wave
from pathlib import Path

import pytest

from core import media_audio


@pytest.fixture
def executables(monkeypatch):
    binaries = {}
    for name in ("ffmpeg", "ffprobe"):
        program = os.environ.get(f"WHISPER_SMOKE_{name.upper()}") or shutil.which(name)
        if not program:
            pytest.skip(f"{name} is unavailable")
        binaries[name] = program
    monkeypatch.setattr(media_audio, "bundled_binary", binaries.__getitem__)
    return binaries


def test_selected_audio_keeps_its_delayed_start(tmp_path, executables):
    source = tmp_path / "音声 commentary.mkv"
    subprocess.run(
        [executables["ffmpeg"], "-v", "error", "-f", "lavfi", "-i", "anullsrc=r=16000",
         "-itsoffset", "1", "-f", "lavfi", "-i", "sine=440:sample_rate=16000:duration=1",
         "-t", "2", "-map", "0:a", "-map", "1:a", "-metadata:s:a:0", "language=eng",
         "-metadata:s:a:1", "language=jpn", "-metadata:s:a:1", "title=Commentary",
         "-disposition:a:0", "0", "-disposition:a:1", "default", "-c:a", "pcm_s16le", str(source)],
        check=True,
    )
    tracks = media_audio.probe_audio_tracks(str(source))
    assert tracks == [
        media_audio.AudioTrack(0, "eng", "", 2, False),
        media_audio.AudioTrack(1, "jpn", "Commentary", 1, True),
    ]
    assert media_audio.default_audio_track(tracks) == 1
    target = media_audio.prepare_audio_track(str(source), 1, tmp_path, lambda: False)
    with wave.open(str(target), "rb") as audio:
        assert audio.getnframes() == 32000
        assert not any(audio.readframes(16000))
        assert any(audio.readframes(16000))
    target = media_audio.prepare_audio_track(str(source), 0, tmp_path, lambda: False)
    with wave.open(str(target), "rb") as audio:
        assert not any(audio.readframes(32000))


def test_failed_selected_track_leaves_no_copy(tmp_path, executables):
    source = tmp_path / "invalid.mkv"
    source.write_bytes(b"invalid")
    with pytest.raises(media_audio.AudioPreparationError):
        media_audio.prepare_audio_track(str(source), 1, tmp_path, lambda: False)
    assert list(tmp_path.iterdir()) == [Path(source)]
