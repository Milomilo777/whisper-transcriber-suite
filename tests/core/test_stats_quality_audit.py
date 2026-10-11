"""Usage stats and history for runs without speech: language and duration."""
import json
from types import SimpleNamespace

import core.stats as stats
from app.services.transcription_service import TranscriptionService


class FakeTask:
    def __init__(self):
        self.file_path = "test"
        self.output_paths = []
        self.word_count = 0
        self.audio_duration = 0.0
        self.start_time = None
        self.detected_language = ""
        self.language_probability = 0.0
        self.no_speech = False


def test_stats_language_cleared_only_on_no_speech(monkeypatch):
    task = FakeTask()
    task.detected_language = "fr"
    task.language_probability = 0.0
    task.no_speech = False

    svc = TranscriptionService(SimpleNamespace(app_config={"telemetry_opt_in": True, "stats_url": "http://fake"}))  # type: ignore[arg-type]
    # _post_usage_stats reads the engine snapshot for the payload.
    monkeypatch.setattr(svc, "_engine_snapshot", lambda: {"spawn_backend": "faster_whisper", "model_name": "test_model"})

    posted_payloads = []

    def fake_post_stats_async(config, payload, **kwargs):
        posted_payloads.append(payload)

    monkeypatch.setattr(stats, "post_stats_async", fake_post_stats_async)

    svc._post_usage_stats(task, word_count=5, audio_duration=10.0)
    assert posted_payloads[0]["language"] == "fr"
    posted_payloads.clear()

    task.no_speech = True
    svc._post_usage_stats(task, word_count=0, audio_duration=10.0)
    assert posted_payloads[0]["language"] == ""
    posted_payloads.clear()

    task.no_speech = False
    task.language_probability = 0.9
    svc._post_usage_stats(task, word_count=5, audio_duration=10.0)
    assert posted_payloads[0]["language"] == "fr"


def test_derive_transcript_stats_keeps_duration_for_no_speech():
    svc = TranscriptionService(None)  # type: ignore[arg-type]

    t = FakeTask()
    t.audio_duration = 120.0
    t.no_speech = False
    assert svc._derive_transcript_stats(t) == (0, 120.0)

    t2 = FakeTask()
    t2.audio_duration = 12.5
    t2.no_speech = True
    assert svc._derive_transcript_stats(t2) == (0, 12.5)


def test_old_worker_fallback_parses_file(tmp_path):
    svc = TranscriptionService(None)  # type: ignore[arg-type]

    t = FakeTask()
    t.no_speech = False
    json_path = tmp_path / "test.json"
    json_path.write_text(json.dumps([{"text": "Hello world", "start": 0.0, "end": 2.5}]), encoding="utf-8")
    t.output_paths = [str(json_path)]
    t.file_path = str(json_path).replace(".json", ".mp3")

    assert svc._derive_transcript_stats(t) == (2, 2.5)
