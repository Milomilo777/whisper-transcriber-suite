import subprocess
import os

import pytest

from core.failure_clue import observed_code
from core import _checkpoint, media_audio, transcriber
from core.task import TranscriptionTask


def test_probe_container_damage_is_classified(tmp_path, monkeypatch):
    path = tmp_path / "missing-moov.mp4"
    path.touch()
    monkeypatch.setattr(
        transcriber.subprocess, "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            args[0], 1, "", "[mov,mp4 @ 00001] moov atom not found\n",
        ),
    )
    try:
        transcriber.get_duration(str(path))
    except RuntimeError as error:
        assert observed_code(error) == "av_invalid_data"
    else:
        raise AssertionError("the broken file was accepted")


def test_repair_preflights_free_space(tmp_path, monkeypatch):
    path = tmp_path / "bad.mp4"
    path.write_bytes(b"keep")
    monkeypatch.setattr(media_audio.shutil, "disk_usage", lambda folder: type("Disk", (), {"free": 0})())
    with pytest.raises(media_audio.RepairSpaceError):
        media_audio.repair_audio(str(path), 0, tmp_path / "copies", lambda: False)
    assert not list((tmp_path / "copies").iterdir())
    assert path.read_bytes() == b"keep"


def test_repair_checkpoint_cannot_mix_original_and_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(_checkpoint, "partials_dir", lambda: tmp_path)
    task = TranscriptionTask("talk.mp4")
    task.repair_name = "repaired-audio-123-abcd1234.wav"
    assert transcriber._checkpoint_track_problem(task, {})
    assert transcriber._checkpoint_track_problem(task, {"repair_name": "other.wav"})
    copy = tmp_path / task.repair_name
    copy.write_bytes(b"keep")
    saved = {"repair_name": task.repair_name, "repair_identity": list(media_audio.repair_identity(copy))}
    assert not transcriber._checkpoint_track_problem(task, saved)
    copy.write_bytes(b"new!")
    changed = saved["repair_identity"][1] + 2_000_000_000
    os.utime(copy, ns=(changed, changed))
    assert transcriber._checkpoint_track_problem(task, saved)


def test_audio_copy_sweep_avoids_live_workers_and_unrelated_files(tmp_path, monkeypatch):
    monkeypatch.setattr(_checkpoint, "partials_dir", lambda: tmp_path)
    monkeypatch.setattr("core._proc.pid_may_be_alive", lambda pid: pid == 20)
    for name in ("audio-copy-20-abcd1234.wav", "audio-copy-21-abcd1234.wav",
                 "repaired-audio-22-abcd1234.wav", "owner.wav"):
        path = tmp_path / name
        path.touch()
        os.utime(path, (1, 1))
    assert _checkpoint.sweep_partials() == 2
    assert {path.name for path in tmp_path.iterdir()} == {"audio-copy-20-abcd1234.wav", "owner.wav"}
