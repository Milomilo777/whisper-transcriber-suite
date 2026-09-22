"""Tests for app.services.transcription_service's stats wiring.

Covers ``_derive_transcript_stats`` (word-count recovery across every
output-format combination, not just "json") and ``_post_usage_stats``
(payload shape + genuine no-op when telemetry is off). This is the exact
seam a real bug shipped through unnoticed: word_count silently read 0
whenever a user's output_formats didn't include "json" (fixed in v1.5.0,
see docs/CHANGELOG.md).
"""
from __future__ import annotations

import json
import time
from types import SimpleNamespace

from app.services.transcription_service import TranscriptionService
from core import stats as core_stats

SRT_TWO_WORDS = "1\n00:00:00,000 --> 00:00:02,000\nHello world\n\n"


def _service(app_config: dict | None = None) -> TranscriptionService:
    return TranscriptionService(SimpleNamespace(app_config=app_config or {}))


def _write_json_segments(path, segments) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(segments, f)


# ---------------------------------------------------------------- _derive_transcript_stats


def test_derive_stats_from_json_sidecar_in_output_paths(tmp_path):
    json_path = tmp_path / "clip.json"
    _write_json_segments(json_path, [{"start": 0.0, "end": 2.5, "text": "Hello world"}])
    task = SimpleNamespace(output_paths=[str(json_path)], file_path=str(tmp_path / "clip.mp4"))

    word_count, duration = _service()._derive_transcript_stats(task)

    assert word_count == 2
    assert duration == 2.5


def test_derive_stats_falls_back_to_json_next_to_source_when_not_in_output_paths(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"")
    _write_json_segments(tmp_path / "clip.json", [{"start": 0.0, "end": 1.0, "text": "one two three"}])
    task = SimpleNamespace(output_paths=[], file_path=str(media))

    word_count, duration = _service()._derive_transcript_stats(task)

    assert word_count == 3
    assert duration == 1.0


def test_derive_stats_falls_back_to_srt_when_json_not_among_output_formats(tmp_path):
    """The real bug: a user whose output_formats is just ["srt"] used to get
    word_count=0 forever, no matter how much was actually transcribed."""
    srt_path = tmp_path / "clip.srt"
    srt_path.write_text(SRT_TWO_WORDS, encoding="utf-8")
    task = SimpleNamespace(output_paths=[str(srt_path)], file_path=str(tmp_path / "clip.mp4"))

    word_count, duration = _service()._derive_transcript_stats(task)

    assert word_count == 2
    assert duration == 2.0


def test_derive_stats_returns_zero_when_nothing_parseable_was_produced(tmp_path):
    """Only a .docx was produced -- not in core.convert's PARSE_FORMATS."""
    docx_path = tmp_path / "clip.docx"
    docx_path.write_bytes(b"not a real docx")
    task = SimpleNamespace(output_paths=[str(docx_path)], file_path=str(tmp_path / "clip.mp4"))

    assert _service()._derive_transcript_stats(task) == (0, 0.0)


def test_derive_stats_prefers_worker_reported_numbers_over_file_parsing(tmp_path):
    """A docx/pdf/txt-only run has no parseable output file, but the worker
    now reports word_count/audio_duration in its "done" event (stored on the
    task) -- those must win, with no file access needed."""
    docx_path = tmp_path / "clip.docx"
    docx_path.write_bytes(b"not a real docx")
    task = SimpleNamespace(
        output_paths=[str(docx_path)],
        file_path=str(tmp_path / "clip.mp4"),
        word_count=57,
        audio_duration=123.4,
    )

    assert _service()._derive_transcript_stats(task) == (57, 123.4)


def test_derive_stats_zero_worker_count_still_falls_back_to_files(tmp_path):
    """An older worker never sends the fields (task keeps word_count=0) --
    the file-based fallback must still run and find the real words."""
    json_path = tmp_path / "clip.json"
    _write_json_segments(json_path, [{"start": 0.0, "end": 2.5, "text": "Hello world"}])
    task = SimpleNamespace(
        output_paths=[str(json_path)],
        file_path=str(tmp_path / "clip.mp4"),
        word_count=0,
        audio_duration=0.0,
    )

    assert _service()._derive_transcript_stats(task) == (2, 2.5)


def test_derive_stats_skips_a_listed_path_that_does_not_exist_on_disk(tmp_path):
    missing = tmp_path / "gone.srt"  # listed but never actually written
    real_json = tmp_path / "clip.json"
    _write_json_segments(real_json, [{"start": 0.0, "end": 4.0, "text": "a b c d"}])
    task = SimpleNamespace(
        output_paths=[str(missing), str(real_json)],
        file_path=str(tmp_path / "clip.mp4"),
    )

    word_count, duration = _service()._derive_transcript_stats(task)

    assert word_count == 4
    assert duration == 4.0


def test_derive_stats_never_raises_on_a_task_with_no_paths_at_all():
    task = SimpleNamespace(output_paths=None, file_path="")
    assert _service()._derive_transcript_stats(task) == (0, 0.0)


def test_derive_stats_ignores_a_malformed_json_sidecar_that_is_not_a_list(tmp_path):
    json_path = tmp_path / "clip.json"
    json_path.write_text(json.dumps({"not": "a list"}), encoding="utf-8")
    task = SimpleNamespace(output_paths=[str(json_path)], file_path=str(tmp_path / "clip.mp4"))

    assert _service()._derive_transcript_stats(task) == (0, 0.0)


# ---------------------------------------------------------------- _post_usage_stats


def test_post_usage_stats_builds_the_expected_payload(monkeypatch):
    captured: dict = {}

    def _fake_post_stats_async(config, payload, **kwargs):
        captured["config"] = config
        captured["payload"] = payload
        return True

    monkeypatch.setattr(core_stats, "post_stats_async", _fake_post_stats_async)
    monkeypatch.setattr(time, "time", lambda: 142.0)

    app_config = {
        "telemetry_opt_in": True,
        "stats_url": "https://example/stats",
        "model": {"name": "large-v3"},
    }
    task = SimpleNamespace(
        file_path="/media/some clip.mp4",
        detected_language="fa",
        status="done",
        start_time=100.0,
    )

    _service(app_config)._post_usage_stats(task, word_count=17, audio_duration=30.0)

    assert captured["config"] is app_config
    payload = captured["payload"]
    assert payload["word_count"] == "17"
    assert payload["audio_duration"] == "30.000"
    assert payload["transcription_time"] == "42.000"
    assert payload["language"] == "fa"
    assert payload["status"] == "done"
    assert payload["model"] == "large-v3"
    assert payload["file_name"] == "some clip.mp4"  # basename only -- no local path leak


def test_post_usage_stats_reports_the_engine_model_for_alt_backends(monkeypatch):
    """An NVIDIA/cloud/whisper.cpp run must not claim the Whisper model
    name -- those engines never touch it."""
    captured: dict = {}

    def _fake_post_stats_async(config, payload, **kwargs):
        captured["payload"] = payload
        return True

    monkeypatch.setattr(core_stats, "post_stats_async", _fake_post_stats_async)

    app_config = {
        "telemetry_opt_in": True,
        "stats_url": "https://example/stats",
        "model": {"name": "large-v3"},
        "transcribe_backend": "nvidia_asr",
        "nvidia_asr_model_id": "nvidia/nemotron-3.5-asr-streaming-0.6b",
    }
    task = SimpleNamespace(file_path="a.mp4", detected_language="", status="finished", start_time=0.0)

    _service(app_config)._post_usage_stats(task, word_count=25, audio_duration=9.7)
    assert captured["payload"]["model"] == (
        "nvidia_asr:nvidia/nemotron-3.5-asr-streaming-0.6b"
    )

    app_config["transcribe_backend"] = "whisper_cpp"
    _service(app_config)._post_usage_stats(task, word_count=25, audio_duration=9.7)
    assert captured["payload"]["model"] == "whisper_cpp"


def test_post_usage_stats_falls_back_to_whisper_model_key_when_model_dict_is_absent():
    captured: dict = {}
    app_config = {
        "telemetry_opt_in": False,  # keep this hermetic -- see the no-op test below
        "whisper_model": "medium",
    }
    task = SimpleNamespace(file_path="a.mp4", detected_language="en", status="done", start_time=0.0)

    # telemetry is off, so post_stats_async is a real no-op -- this just
    # proves the model fallback + the call itself never raises.
    _service(app_config)._post_usage_stats(task, word_count=1, audio_duration=1.0)
    assert not captured  # nothing was captured because nothing mocked was called


def test_post_usage_stats_is_a_genuine_noop_when_telemetry_is_off(monkeypatch):
    def _urlopen_must_not_be_called(*_a, **_kw):
        raise AssertionError("network path reached despite telemetry_opt_in=False")

    monkeypatch.setattr(core_stats.urllib.request, "urlopen", _urlopen_must_not_be_called)

    app_config = {"telemetry_opt_in": False, "stats_url": "https://example/stats"}
    task = SimpleNamespace(file_path="clip.mp4", detected_language="en", status="done", start_time=0.0)

    # Real post_stats_async (NOT mocked) -- must return without ever posting.
    _service(app_config)._post_usage_stats(task, word_count=5, audio_duration=1.0)


def test_post_usage_stats_never_raises_even_if_task_is_missing_fields():
    task = SimpleNamespace()  # no file_path / start_time / detected_language / status
    _service({"telemetry_opt_in": False})._post_usage_stats(task, word_count=0, audio_duration=0.0)


# ---------------------------------------------------------------- finish_task / stats gating


def test_finish_task_skips_usage_stats_post_for_an_errored_task(monkeypatch):
    """The real bug found live in the deployed stats: a task that failed
    (e.g. the configured backend had no valid key) never produced a real
    transcript, but finish_task used to POST usage stats for it anyway --
    a fake "0 words, 0:00" row indistinguishable from a genuine empty
    transcription. history.finish_transcription() still records the real
    status locally; only the external usage-stats POST must be skipped."""
    app = SimpleNamespace(app_config={}, update_overall_progress=lambda: None)
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    posted: list = []
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: posted.append(a))
    task = SimpleNamespace(
        status="error", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=[], file_path="clip.mp4", history_id=0, source_download=None,
    )
    worker = {"task": task, "temporary": False}

    svc.finish_task(worker, keep_status=True)

    assert posted == [], "an errored task must not post usage stats"
    assert task.status == "error", "keep_status=True must not overwrite the real status"


def test_finish_task_posts_usage_stats_for_a_genuine_successful_completion(monkeypatch):
    app = SimpleNamespace(
        app_config={},
        update_overall_progress=lambda: None,
        show_last_result=lambda task: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    posted: list = []
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: posted.append(a))
    task = SimpleNamespace(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=[], file_path="clip.mp4", history_id=0, source_download=None,
    )
    worker = {"task": task, "temporary": False}

    svc.finish_task(worker, keep_status=False)

    assert len(posted) == 1, "a genuine completion must still post usage stats"
    assert task.status == "finished"


def test_finish_task_persists_history_with_the_real_terminal_status(monkeypatch):
    """Found by an adversarial review (2026-09-22) alongside the
    persist-before-report reorder below: the history write was moved to
    run BEFORE task.status is flipped to "finished" -- naively reusing
    task.status at that point would have recorded whatever status the
    task held mid-run (e.g. "running") instead of the real outcome."""
    app = SimpleNamespace(
        app_config={}, update_overall_progress=lambda: None,
        show_last_result=lambda task: None,
    )
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: None)
    recorded: list = []
    history = SimpleNamespace(
        finish_transcription=lambda *a, **k: (recorded.append(k), True)[1]
    )
    app.history = history
    task = SimpleNamespace(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=["clip.srt"], file_path="clip.mp4", history_id=7,
        source_download=None, detected_language="",
    )
    worker = {"task": task, "temporary": False}

    svc.finish_task(worker, keep_status=False)

    assert recorded and recorded[0]["status"] == "finished"
    assert task.status == "finished"


def test_finish_task_persists_history_before_reporting_success(monkeypatch):
    """The ordering half of the same fix: history.finish_transcription
    must be called BEFORE show_last_result, so a durable-write failure
    is never masked by an already-shown success card."""
    app = SimpleNamespace(app_config={}, update_overall_progress=lambda: None)
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: None)
    order: list[str] = []
    app.history = SimpleNamespace(
        finish_transcription=lambda *a, **k: (order.append("history"), True)[1]
    )
    app.show_last_result = lambda task: order.append("show_last_result")
    task = SimpleNamespace(
        status="running", cancelled=False, end_time=None, start_time=time.time(),
        output_paths=["clip.srt"], file_path="clip.mp4", history_id=7,
        source_download=None, detected_language="",
    )
    worker = {"task": task, "temporary": False}

    svc.finish_task(worker, keep_status=False)

    assert order == ["history", "show_last_result"]


def test_finish_task_skips_usage_stats_post_for_a_cancelled_task(monkeypatch):
    app = SimpleNamespace(app_config={}, update_overall_progress=lambda: None)
    svc = TranscriptionService(app)  # type: ignore[arg-type]
    posted: list = []
    monkeypatch.setattr(svc, "_post_usage_stats", lambda *a, **k: posted.append(a))
    task = SimpleNamespace(
        status="cancelled", cancelled=True, end_time=None, start_time=time.time(),
        output_paths=[], file_path="clip.mp4", history_id=0, source_download=None,
    )
    worker = {"task": task, "temporary": False}

    svc.finish_task(worker, keep_status=False)

    assert posted == [], "a user-cancelled task has no real transcript to report"
