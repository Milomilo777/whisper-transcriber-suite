import time
import wave
from pathlib import Path

from core.task import TranscriptionTask, apply_run_options, task_run_options
from core import _checkpoint, media_audio, transcriber
from core.media_audio import AudioTrack, default_audio_track
from app.services.transcription_service import transcribe_command


def test_audio_track_round_trips_through_history_options():
    original = TranscriptionTask("lecture.mkv")
    original.audio_track = 1
    restored = TranscriptionTask(original.file_path)
    apply_run_options(restored, task_run_options(original))
    assert restored.audio_track == 1


def test_legacy_history_keeps_automatic_track():
    task = TranscriptionTask("lecture.mkv")
    apply_run_options(task, {})
    assert task.audio_track is None


def test_track_default_and_worker_command():
    tracks = [AudioTrack(0, "eng", "", 2, False), AudioTrack(1, "jpn", "Commentary", 1, True)]
    task = TranscriptionTask("lecture.mkv")
    task.audio_track = default_audio_track(tracks)
    assert transcribe_command(task)["audio_track"] == 1
    assert default_audio_track(tracks[:1]) == 0


def test_checkpoint_rejects_another_track_and_supports_legacy():
    task = TranscriptionTask("lecture.mkv")
    assert transcriber._checkpoint_track_problem(task, {}) == ""
    task.audio_track = 1
    assert transcriber._checkpoint_track_problem(task, {"audio_track": 0})
    assert transcriber._checkpoint_track_problem(task, {"audio_track": True})
    assert transcriber._checkpoint_track_problem(task, {})
    assert transcriber._checkpoint_track_problem(task, {"audio_track": 1}) == ""


def test_completed_resume_prepares_saved_track_for_postprocessing(tmp_path, monkeypatch):
    source = tmp_path / "lesson.mkv"
    source.touch()
    temp = tmp_path / "chosen.wav"
    with wave.open(str(temp), "wb") as audio:
        audio.setparams((1, 2, 16000, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 32000)
    monkeypatch.setattr(_checkpoint, "partials_dir", lambda: tmp_path)
    monkeypatch.setattr(transcriber, "config", {"output_formats": ["json"]})
    _checkpoint.write_checkpoint(
        str(source), backend="faster_whisper", model_name="tiny", language="en",
        language_probability=1, cfg_fingerprint="old", last_end_time=1,
        segments=[{"start": 0, "end": 1, "text": "Saved text"}],
        checkpoint_time=time.time(), transcription_completed=True, audio_track=1,
    )
    seen = []

    def prepare(path, ordinal, folder, cancelled):
        seen.append((path, ordinal))
        return temp

    def postprocess(task, *args):
        assert Path(transcriber._audio_input(task)) == temp
        return 0

    monkeypatch.setattr(media_audio, "prepare_audio_track", prepare)
    monkeypatch.setattr(transcriber, "_run_post_pipeline", postprocess)
    task = TranscriptionTask(str(source))
    assert transcriber.resume_transcription(task)
    assert seen == [(str(source), 1)]
    assert not temp.exists()
    assert '"audio_track": 1' in source.with_suffix(".json").read_text(encoding="utf-8")
