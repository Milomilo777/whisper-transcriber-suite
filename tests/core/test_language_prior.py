"""Hermetic language-prior decisions and real transcriber wiring; no Tk or real model."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import language_prior as prior


INCIDENT = [
    {"cy": 0.80, "en": 0.20},
    {"en": 0.57, "cy": 0.43},
    {"cy": 0.72, "en": 0.28},
    {"cy": 0.92, "en": 0.07},
    {"cy": 0.86, "en": 0.14},
    {"en": 0.97, "cy": 0.01},
]


class FakeDetector:
    def __init__(self, windows):
        self.windows = iter(windows)
        self.calls = []

    def detect_language(self, *, audio):
        self.calls.append(audio)
        probabilities = next(self.windows)
        language = max(probabilities, key=probabilities.get)
        return language, probabilities[language], list(probabilities.items())


def test_incident_six_windows_overrides_welsh():
    # The supplied six measurements test aggregation directly; production samples five.
    detector = FakeDetector(INCIDENT)
    windows = [dict(detector.detect_language(audio=t)[2]) for t in (0, 60, 300, 600, 1200, 1800)]
    result = prior.choose_language(windows, {"en", "fa"})
    assert result.language == "en"
    assert result.reason == "prior_override"
    assert result.probability == pytest.approx(2.23 / 5.97)
    assert result.shares["cy"] == pytest.approx(3.74 / 5.97)
    assert result.window_count == 6


def test_clear_welsh_stays_welsh():
    result = prior.choose_language([{"cy": 0.98, "en": 0.01, "fa": 0.01}] * 5, {"en", "fa"})
    assert result.language == "cy"
    assert result.reason == "winner"
    assert result.probability == pytest.approx(0.98)


def test_winner_already_plausible_is_unchanged():
    result = prior.choose_language([{"fa": 0.60, "en": 0.40}] * 5, {"fa", "en"})
    assert result.language == "fa"
    assert result.reason == "winner"
    assert result.probability == pytest.approx(0.60)


def test_english_always_plausible_with_persian_only_history():
    result = prior.choose_language([{"en": 0.98, "fa": 0.02}] * 5, {"fa"})
    assert result.language == "en"
    assert result.reason == "winner"
    assert result.probability == pytest.approx(0.98)
    # Also prove the unconditional English prior matters when the winner is rare.
    assert prior.choose_language(INCIDENT, {"fa"}).language == "en"


@pytest.mark.parametrize("share,expected", [(0.249, "cy"), (0.25, "en"), (0.251, "en")])
def test_override_threshold_is_inclusive(share, expected):
    assert prior.choose_language([{"cy": 1 - share, "en": share}], {"en"}).language == expected


def test_prior_uses_best_plausible_individual_share():
    # Combined plausible mass is insufficient if no individual language reaches 25%.
    result = prior.choose_language([{"cy": 0.6, "en": 0.2, "fa": 0.2}], {"fa"})
    assert result.language == "cy"
    result = prior.choose_language([{"cy": 0.4, "fa": 0.35, "en": 0.25}], {"fa"})
    assert result.language == "fa"


@pytest.mark.parametrize("duration,length", [(1, 1), (29, 29), (30, 30), (149.9, 30)])
def test_short_audio_one_window_from_start(duration, length):
    calls = []
    result = prior.detect_with_prior(duration, {"fa"},
                                    lambda start, span: calls.append((start, span)) or {"en": 1.0})
    assert calls == [(0.0, length)]
    assert result.window_count == 1


@pytest.mark.parametrize("duration", [150, 300, 1980])
def test_five_windows_at_percentile_centers(duration):
    windows = prior.sample_windows(duration)
    assert len(windows) == 5
    assert [start + length / 2 for start, length in windows] == pytest.approx(
        [duration * p for p in (0.1, 0.3, 0.5, 0.7, 0.9)])
    assert all(0 <= start < start + length <= duration for start, length in windows)


def test_deterministic_including_ties_and_mapping_order():
    baseline = prior.choose_language(INCIDENT, {"en", "fa"})
    for _ in range(10):
        assert prior.choose_language([dict(reversed(list(row.items()))) for row in INCIDENT],
                                     ["fa", "en"]) == baseline
    assert sum(baseline.shares.values()) == pytest.approx(1)
    assert prior.choose_language([{"fa": 0.5, "en": 0.5}], {"fa"}).language == "en"


@pytest.mark.parametrize("rows", [[], [{}], [{"en": 0}], [{"en": -1}],
                                   [{"en": float("nan")}], [{"en": float("inf")}]])
def test_invalid_probability_mass_raises(rows):
    with pytest.raises(ValueError):
        prior.choose_language(rows, {"en"})


@pytest.fixture
def wiring(monkeypatch, tmp_path):
    from core import transcriber as t
    from core.task import TranscriptionTask
    from app import i18n

    task = TranscriptionTask(str(tmp_path / "talk.wav"))
    (tmp_path / "talk.wav").write_bytes(b"fake")
    cfg = {"transcribe_backend": "faster_whisper", "ui_language": "en", "loop_guard_repeats": 0}
    monkeypatch.setattr(t, "config", cfg.copy())
    monkeypatch.setattr(t, "_runtime_overrides_scope", lambda task: nullcontext(cfg))
    monkeypatch.delenv("WTS_UI_LANGUAGE", raising=False)
    monkeypatch.setattr(i18n, "setting_language", lambda value: value)
    monkeypatch.setattr(t, "MODEL_READY", True)
    monkeypatch.setattr(t, "MODEL_ERROR", None)
    monkeypatch.setattr(t, "PIPELINE", None)
    monkeypatch.setattr(t, "require_audio_stream", lambda path: None)
    monkeypatch.setattr(t, "get_duration", lambda path: 300.0)
    monkeypatch.setattr(t, "_run_post_pipeline", lambda *args: 0)
    monkeypatch.setattr(t, "_write_outputs", lambda *args, **kwargs: [])
    reads = []
    monkeypatch.setattr(t, "_read_language_window",
                        lambda path, start, length: reads.append((path, start, length)) or start)
    return t, task, cfg, reads


@pytest.mark.parametrize("batched", [False, True])
def test_transcribe_forces_choice_reports_share_and_persists_before_done(wiring, monkeypatch, caplog, batched):
    t, task, cfg, reads = wiring
    detector = FakeDetector([{"cy": 0.63, "en": 0.37}] * 5)
    calls, reported, checkpoints, order, logs = [], [], [], [], []

    def transcribe(path, **kwargs):
        calls.append((path, kwargs))
        return iter([SimpleNamespace(start=0.0, end=5.0, text="hello", words=[])]), SimpleNamespace(
            language=kwargs["language"], language_probability=1.0)

    detector.transcribe = transcribe
    monkeypatch.setattr(t, "MODEL", detector)
    if batched:
        # Detection must use the loaded WhisperModel, never the pipeline wrapper.
        monkeypatch.setattr(t, "PIPELINE", SimpleNamespace(transcribe=transcribe))
    monkeypatch.setattr(t, "_write_periodic_checkpoint",
                        lambda *args, **kwargs: checkpoints.append((args[3], args[4])))
    monkeypatch.setattr(t, "_write_outputs", lambda *args, **kwargs: order.append("save") or [])
    with caplog.at_level(logging.INFO):
        t.transcribe(task, lambda percent: order.append(percent), logs.append,
                     lambda code, probability: reported.append((code, probability)))
    assert calls[0][1]["language"] == "en"
    assert ("batch_size" in calls[0][1]) is batched
    assert reported == [("en", pytest.approx(0.37))]
    assert task.detected_language == "en" and task.language_probability == pytest.approx(0.37)
    assert checkpoints[-1] == ("en", pytest.approx(0.37))
    assert order.index("save") < order.index(100)
    assert len(reads) == len(detector.calls) == 5
    records = [r.message for r in caplog.records if "language_prior windows=" in r.message]
    assert len(records) == 1 and "windows=5" in records[0] and "reason=prior_override" in records[0]
    assert "cy=0.630, en=0.370" in records[0]
    assert len([line for line in logs if "Auto language: using en" in line]) == 1


@pytest.mark.parametrize("failure", ["sampling", "detector", "empty"])
def test_detector_or_sampling_failure_falls_back_to_engine(wiring, monkeypatch, caplog, failure):
    t, task, cfg, reads = wiring
    calls = []

    def broken(*args, **kwargs):
        raise RuntimeError("injected detection failure")

    detector = FakeDetector([{}])
    if failure == "detector":
        detector.detect_language = broken
    elif failure == "sampling":
        monkeypatch.setattr(t, "_read_language_window", broken)

    def transcribe(path, **kwargs):
        calls.append(kwargs)
        return iter([]), SimpleNamespace(language="cy", language_probability=0.85)

    detector.transcribe = transcribe
    monkeypatch.setattr(t, "MODEL", detector)
    with caplog.at_level(logging.INFO):
        t.transcribe(task, log_cb=lambda line: None)
    assert "language" not in calls[0]
    assert task.detected_language == "cy" and task.language_probability == 0.85
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "Language prior failed" in r.message]
    assert len(warnings) == 1 and warnings[0].exc_info
    assert "reason=fallback" in caplog.text


@pytest.mark.parametrize("changes,backend", [
    ({"language": "fa"}, "faster_whisper"),
    ({"language": "invalid"}, "faster_whisper"),
    ({"languages": ("fa", "en")}, "faster_whisper"),
    ({"whisper_task": "translate"}, "faster_whisper"),
    ({"resume": True, "detected_language": "fa"}, "faster_whisper"),
    ({}, "whisper_cpp"),
])
def test_ineligible_tasks_do_not_use_module(wiring, monkeypatch, changes, backend):
    t, task, cfg, reads = wiring
    for key, value in changes.items():
        setattr(task, key, value)

    def forbidden(*args, **kwargs):
        pytest.fail("language prior module was used for an ineligible task")

    monkeypatch.setattr(prior, "detect_with_prior", forbidden)
    kwargs = t._build_transcribe_kwargs(task)
    original = kwargs.copy()
    assert t._apply_language_prior(task, object(), task.file_path, 300, cfg, kwargs, None,
                                   backend_name=backend) is None
    assert kwargs == original and not reads


@pytest.mark.parametrize("clip_start,clip_end,span", [(100, 400, 300), (100, None, 900),
                                                     (900, 2000, 100), (100, 120, 20)])
def test_clip_sampling_is_bounded_and_uses_the_slice(wiring, monkeypatch, clip_start, clip_end, span):
    t, task, cfg, reads = wiring
    task.clip_start, task.clip_end = clip_start, clip_end
    monkeypatch.setattr(t, "get_duration", lambda path: 1000.0)
    slice_path = str(Path(task.file_path).with_name("slice.wav"))
    monkeypatch.setattr(t, "_slice_audio_from", lambda *args, **kwargs: slice_path)
    model = FakeDetector([{"en": 1.0}] * 5)
    model.transcribe = lambda *args, **kwargs: (iter([]), SimpleNamespace(language="en", language_probability=1))
    monkeypatch.setattr(t, "MODEL", model)
    t.transcribe(task, log_cb=lambda line: None)
    assert [(start, length) for path, start, length in reads] == prior.sample_windows(span)
    assert all(path == slice_path and start + length <= span for path, start, length in reads)


def test_history_last_twenty_finished_by_completion_time(tmp_path):
    from core.history import HistoryDB

    db = HistoryDB(tmp_path / "history.db")
    try:
        for index in range(25):
            row = db.insert_transcription("file.wav")
            db.finish_transcription(row, "finished", language="cy" if index < 5 else "fa")
        # Completion time, rather than insertion time, determines the most recent jobs.
        db._conn.execute("UPDATE transcriptions SET finished_at=9999999999 WHERE id=1")
        db._conn.commit()
        for _ in range(25):
            row = db.insert_transcription("failed.wav")
            db.finish_transcription(row, "error", language="cy")
        assert db.recent_finished_languages() == ["cy"] + ["fa"] * 19
    finally:
        db.close()


def test_ui_history_and_existing_source_metadata_form_the_prior(wiring, monkeypatch):
    t, task, cfg, reads = wiring
    from core.history import HistoryDB
    cfg["ui_language"] = "de-DE"
    monkeypatch.setattr(HistoryDB, "recent_finished_languages", lambda self, limit: ["fa-IR", "iw"])
    task.source_download = SimpleNamespace(detected_language="pt-BR")
    captured = []

    def capture(duration, plausible, detect):
        captured.append(plausible)
        return prior.choose_language([{"de": 1.0}], plausible)

    monkeypatch.setattr(prior, "detect_with_prior", capture)
    kwargs = {}
    t._apply_language_prior(task, object(), task.file_path, 300, cfg, kwargs, None)
    assert captured == [{"en", "de", "fa", "he", "pt"}]
    assert kwargs == {"language": "de"}


def test_completed_checkpoint_keeps_its_language_without_prior(wiring, monkeypatch):
    t, task, cfg, reads = wiring
    checkpoint = {
        "task": "transcribe", "language": "fa", "language_probability": 0.72,
        "transcription_completed": True,
        "segments": [{"start": 0.0, "end": 5.0, "text": "saved"}],
    }
    task.resume = True
    monkeypatch.setattr(t._checkpoint, "load_checkpoint", lambda path: checkpoint)
    monkeypatch.setattr(t._checkpoint, "validate_checkpoint", lambda *args, **kwargs: None)
    monkeypatch.setattr(t._checkpoint, "media_identity_problem", lambda data: None)
    written, reported = [], []
    monkeypatch.setattr(t, "_write_resumed_outputs", lambda *args: written.append(args[2]))

    def forbidden(*args, **kwargs):
        pytest.fail("checkpoint resume must not call the language prior")

    monkeypatch.setattr(prior, "detect_with_prior", forbidden)
    assert t.resume_transcription(task, log_cb=lambda line: None,
                                  language_cb=lambda *args: reported.append(args)) is True
    assert written == ["fa"] and reported == [("fa", 0.72)]
    assert task.detected_language == "fa" and not reads


def test_audio_reader_uses_one_bounded_seek_and_hidden_process(monkeypatch, tmp_path):
    from core import transcriber as t
    import numpy as np
    calls = []
    monkeypatch.setattr(t, "bundled_binary", lambda name: "ffmpeg")

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=np.array([0.1, 0.2], dtype="<f4").tobytes())

    monkeypatch.setattr(t.subprocess, "run", run)
    audio = t._read_language_window(str(tmp_path / "talk.wav"), 180.0, 30.0)
    command, kwargs = calls[0]
    assert len(calls) == 1
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "180.000000"
    assert command[command.index("-t") + 1] == "30.000000"
    assert command[command.index("-map") + 1] == "0:a:0"
    assert kwargs["stdin"] == t.subprocess.DEVNULL and kwargs["timeout"] == 60
    assert t.new_session_kwargs().items() <= kwargs.items()
    assert audio.tolist() == pytest.approx([0.1, 0.2])
