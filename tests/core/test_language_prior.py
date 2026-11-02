"""Language evidence decisions, transcriber wiring, and optional bundled-media checks."""
from __future__ import annotations

import logging
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import language_prior as prior


INCIDENT = [
    {"cy": 0.80, "en": 0.20}, {"en": 0.57, "cy": 0.43},
    {"cy": 0.72, "en": 0.28}, {"cy": 0.92, "en": 0.07},
    {"cy": 0.86, "en": 0.14}, {"en": 0.97, "cy": 0.01},
]
REAL_TEN_MINUTES = [
    {"cy": 0.61, "en": 0.39}, {"cy": 0.87, "en": 0.13},
    {"cy": 0.89, "en": 0.11}, {"cy": 0.88, "en": 0.12},
    {"cy": 0.92, "en": 0.08},
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


def segment(score, tokens=10):
    return SimpleNamespace(tokens=list(range(tokens)), avg_logprob=score)


class FakeDecoder:
    def __init__(self, scores):
        self.scores = scores
        self.calls = []

    def __call__(self, start, length, language):
        self.calls.append((start, length, language))
        return iter([segment(self.scores[language])])


def forbidden_decode(*args):
    pytest.fail("Clear evidence must not invoke verification")


@pytest.mark.parametrize("scores,language,reason", [
    ({"en": -0.2, "cy": -0.8}, "en", "verified_override"),
    ({"en": -0.8, "cy": -0.2}, "cy", "verified_winner"),
    ({"en": -0.2, "cy": -0.25}, None, "inconclusive"),
])
def test_real_ten_minute_evidence(scores, language, reason):
    detector = FakeDetector(REAL_TEN_MINUTES)
    decoder = FakeDecoder(scores)
    result = prior.detect_with_prior(
        600, {"en"}, lambda start, length: dict(detector.detect_language(audio=start)[2]), decoder)
    assert detector.calls == pytest.approx([45, 165, 285, 405, 525])
    assert decoder.calls == [(165, 30, "cy"), (405, 30, "cy"),
                             (165, 30, "en"), (405, 30, "en")]
    assert result.window_count == 5
    assert result.language == language and result.reason == reason
    assert result.shares == pytest.approx({"en": 0.166, "cy": 0.834})
    assert result.probability == pytest.approx(result.shares[language] if language else 0)
    assert result.scores == scores


def test_incident_six_windows_verified_override():
    result = prior.choose_language(INCIDENT, {"en", "fa"}, lambda code: {"en": -0.2, "cy": -0.8}[code])
    assert result.language == "en" and result.reason == "verified_override"
    assert result.probability == pytest.approx(2.23 / 5.97) and result.window_count == 6


@pytest.mark.parametrize("row,plausible,expected", [
    ({"cy": 0.98, "en": 0.01, "fa": 0.01}, {"en", "fa"}, "cy"),
    ({"ja": 0.97, "en": 0.03}, {"en"}, "ja"),
    ({"fa": 0.6, "en": 0.4}, {"fa"}, "fa"),
    ({"ja": 0.75, "en": 0.25}, {"ja"}, "ja"),
    ({"en": 0.98, "fa": 0.02}, {"fa"}, "en"),
    ({"cy": 0.9, "ja": 0.1}, {"fa"}, "cy"),
])
def test_clear_or_plausible_winner_needs_no_verification(row, plausible, expected):
    result = prior.detect_with_prior(600, plausible, lambda *args: row, forbidden_decode)
    assert result.language == expected and result.reason == "winner"
    assert result.probability == pytest.approx(row[expected]) and result.scores == {}


def test_ambiguous_first_time_japanese_verified_winner():
    decoder = FakeDecoder({"ja": -0.1, "en": -0.8})
    result = prior.detect_with_prior(600, {"en"}, lambda *args: {"ja": 0.75, "en": 0.25}, decoder)
    assert result.language == "ja" and result.reason == "verified_winner"
    assert result.probability == 0.75 and len(decoder.calls) == 4


def test_highest_individual_plausible_share_is_verified():
    codes = []
    result = prior.choose_language([{"cy": 0.6, "fa": 0.25, "en": 0.15}], {"fa"},
                                   lambda code: codes.append(code) or {"cy": -0.9, "fa": -0.2}[code])
    assert result.language == "fa" and result.probability == 0.25 and codes == ["cy", "fa"]


@pytest.mark.parametrize("difference,expected,reason", [
    (0.0, None, "inconclusive"), (0.149, None, "inconclusive"),
    (0.15, "en", "verified_override"), (-0.149, None, "inconclusive"),
    (-0.15, "cy", "verified_winner"),
])
def test_verification_margin(difference, expected, reason):
    result = prior.choose_language([{"cy": 0.8, "en": 0.2}], {"en"},
                                   lambda code: difference if code == "en" else 0.0)
    assert result.language == expected and result.reason == reason


@pytest.mark.parametrize("share,verified", [(0.049, False), (0.05, True)])
def test_ambiguity_boundary(share, verified):
    calls = []
    result = prior.choose_language([{"cy": 1 - share, "en": share}], {"en"},
                                   lambda code: calls.append(code) or (-0.1 if code == "en" else -0.8))
    assert bool(calls) == verified
    assert result.reason == ("verified_override" if verified else "winner")


def test_token_weighted_scores_across_both_windows():
    def decode(start, length, language):
        # Unweighted means would prefer cy; pooled token weighting prefers en.
        if language == "cy":
            return iter([segment(-0.1, 1), segment(-1.0, 99)])
        return iter([segment(-0.5 if start == 165 else -0.3, 10)])
    result = prior.detect_with_prior(600, {"en"}, lambda *args: REAL_TEN_MINUTES[0], decode)
    assert result.language == "en" and result.reason == "verified_override"
    assert result.scores == pytest.approx({"cy": -0.991, "en": -0.4})


@pytest.mark.parametrize("failure", ["call", "iterator", "empty", "nan"])
def test_decoder_failure_returns_no_decision(failure):
    def decode(*args):
        if failure == "call":
            raise RuntimeError("broken decoder")
        if failure == "empty":
            return iter([])
        if failure == "nan":
            return iter([segment(float("nan"))])
        def broken():
            yield segment(-0.2)
            raise RuntimeError("lazy decode failed")
        return broken()
    result = prior.detect_with_prior(600, {"en"}, lambda *args: REAL_TEN_MINUTES[0], decode)
    assert result.language is None and result.reason == "fallback" and result.error


@pytest.mark.parametrize("valid_count", [0, 1, 2, 3, 4])
def test_bad_windows_skipped_and_minimum_three_required(valid_count):
    calls, skipped = [], []
    def detect(start, length):
        calls.append(start)
        if len(calls) > valid_count:
            raise prior.WindowReadError("empty or unreadable")
        return {"en": 1.0}
    result = prior.detect_with_prior(600, {"en"}, detect, forbidden_decode, on_skip=skipped.append)
    assert len(calls) == 5 and len(skipped) == 5 - valid_count
    assert result.window_count == valid_count
    assert result.language == ("en" if valid_count >= 3 else None)
    assert result.reason == ("winner" if valid_count >= 3 else "fallback")


def test_verification_uses_valid_windows_when_preferred_samples_fail():
    decoder = FakeDecoder({"en": -0.2, "cy": -0.8})
    def detect(start, length):
        if start in (165, 405):
            raise prior.WindowReadError("failed preferred window")
        return REAL_TEN_MINUTES[0]
    result = prior.detect_with_prior(600, {"en"}, detect, decoder)
    assert result.language == "en" and result.window_count == 3
    assert decoder.calls == [(45, 30, "cy"), (285, 30, "cy"),
                             (45, 30, "en"), (285, 30, "en")]


@pytest.mark.parametrize("duration,count", [(1, 1), (29, 1), (30, 1), (59.9, 1),
                                           (60, 3), (100, 3), (149.9, 3), (150, 5), (600, 5)])
def test_short_audio_window_counts(duration, count):
    calls = []
    result = prior.detect_with_prior(duration, {"en"},
        lambda start, length: calls.append((start, length)) or {"en": 1.0}, forbidden_decode)
    assert result.window_count == count and calls == prior.sample_windows(duration)
    assert all(0 <= start < start + length <= duration for start, length in calls)
    if count == 1:
        assert calls == [(0, min(duration, 30))]


@pytest.mark.parametrize("duration", [60, 100, 149.9])
def test_medium_audio_centers_are_clamped(duration):
    expected = [min(max(0, duration * p - 15), duration - 30) for p in (0.1, 0.5, 0.9)]
    assert prior.sample_windows(duration) == [(start, 30) for start in expected]


@pytest.mark.parametrize("duration", [20, 100])
def test_short_audio_can_verify_one_valid_sample(duration):
    decoder = FakeDecoder({"en": -0.2, "cy": -0.8})
    def detect(start, length):
        if duration == 100 and start != 35:
            raise prior.WindowReadError("bad sample")
        return REAL_TEN_MINUTES[0]
    result = prior.detect_with_prior(duration, {"en"}, detect, decoder)
    assert result.window_count == 1 and result.language == "en" and len(decoder.calls) == 2


def test_deterministic_including_ties_and_mapping_order():
    score = lambda code: {"cy": -0.8, "en": -0.2}[code]
    baseline = prior.choose_language(INCIDENT, {"en", "fa"}, score)
    for _ in range(10):
        assert prior.choose_language([dict(reversed(list(row.items()))) for row in INCIDENT],
                                     ["fa", "en"], score) == baseline
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
                        lambda path, start, length, **kw: reads.append((path, start, length)) or start)
    return t, task, cfg, reads


@pytest.mark.parametrize("batched", [False, True])
def test_transcribe_forces_choice_reports_share_and_persists_before_done(wiring, monkeypatch, caplog, batched):
    t, task, cfg, reads = wiring
    detector = FakeDetector([{"cy": 0.63, "en": 0.37}] * 5)
    calls, reported, checkpoints, order, logs = [], [], [], [], []

    def transcribe(path, **kwargs):
        calls.append((path, kwargs))
        if not isinstance(path, str):
            return iter([segment(-0.2 if kwargs["language"] == "en" else -0.8)]), None
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
    assert len(calls) == 5
    for path, options in calls[:4]:
        assert options == dict(language=options["language"], task="transcribe", beam_size=1,
                               best_of=1, temperature=0, without_timestamps=True,
                               condition_on_previous_text=False, vad_filter=False, word_timestamps=False)
    assert [path for path, options in calls[:4]] == [75, 195, 75, 195]
    assert calls[-1][1]["language"] == "en"
    assert ("batch_size" in calls[-1][1]) is batched
    assert reported == [("en", pytest.approx(0.37))]
    assert task.detected_language == "en" and task.language_probability == pytest.approx(0.37)
    assert checkpoints[-1] == ("en", pytest.approx(0.37))
    assert order.index("save") < order.index(100)
    assert len(reads) == len(detector.calls) == 5
    records = [r.message for r in caplog.records if "language_prior windows=" in r.message]
    assert len(records) == 1 and "windows=5" in records[0] and "reason=verified_override" in records[0]
    assert "cy=0.630, en=0.370" in records[0]
    assert "scores=cy=-0.800, en=-0.200" in records[0]
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
    # "cy" finished once (a possible wrong detection) and must not become plausible; "fa" and "he" twice.
    monkeypatch.setattr(HistoryDB, "recent_finished_languages",
                        lambda self, limit: ["cy", "fa-IR", "fa", "iw", "he", ""])
    task.source_download = SimpleNamespace(detected_language="pt-BR")
    captured = []

    def capture(duration, plausible, detect, decode, **kwargs):
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

    def popen(command, **kwargs):
        from io import BytesIO
        calls.append((command, kwargs))
        return SimpleNamespace(stdout=BytesIO(np.array([0.1, 0.2], dtype="<f4").tobytes()),
                               stderr=BytesIO(), wait=lambda **kw: 0, poll=lambda: 0,
                               returncode=0, args=command)

    monkeypatch.setattr(t.subprocess, "Popen", popen)
    audio = t._read_language_window(str(tmp_path / "talk.wav"), 180.0, 30.0)
    command, kwargs = calls[0]
    assert len(calls) == 1
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "180.000000"
    assert command[command.index("-t") + 1] == "30.000000"
    assert command[command.index("-map") + 1] == "0:a:0"
    assert kwargs["stdin"] == t.subprocess.DEVNULL
    assert t.new_session_kwargs().items() <= kwargs.items()
    assert audio.tolist() == pytest.approx([0.1, 0.2])


@pytest.mark.parametrize("outcome", ["inconclusive", "verified_winner", "fallback"])
def test_verification_wiring_preserves_engine_fallback_and_user_log(wiring, monkeypatch, caplog, outcome):
    t, task, cfg, reads = wiring
    detector = FakeDetector(REAL_TEN_MINUTES)
    main_calls, logs = [], []

    def transcribe(path, **kwargs):
        if not isinstance(path, str):
            if outcome == "fallback":
                raise RuntimeError("verification failed")
            score = -0.2 if kwargs["language"] == "cy" else (-0.8 if outcome == "verified_winner" else -0.25)
            return iter([segment(score)]), None
        main_calls.append(kwargs)
        return iter([]), SimpleNamespace(language="cy", language_probability=0.85)

    detector.transcribe = transcribe
    monkeypatch.setattr(t, "MODEL", detector)
    with caplog.at_level(logging.INFO):
        t.transcribe(task, log_cb=logs.append)
    assert ("language" in main_calls[0]) is (outcome == "verified_winner")
    assert task.detected_language == "cy"
    assert task.language_probability == pytest.approx(0.834 if outcome == "verified_winner" else 0.85)
    assert not any("Auto language: using" in line for line in logs)
    records = [r.message for r in caplog.records if "language_prior windows=" in r.message]
    assert len(records) == 1 and f"reason={outcome}" in records[0]
    assert "cy=0.834, en=0.166" in records[0]


@pytest.mark.parametrize("stage", ["sampling", "verification"])
def test_total_deadline_falls_back_without_further_model_calls(wiring, monkeypatch, caplog, stage):
    t, task, cfg, reads = wiring
    now = [0.0]
    monkeypatch.setattr(t, "time", SimpleNamespace(monotonic=lambda: now[0]))
    detector = FakeDetector(REAL_TEN_MINUTES)
    decodes = []
    original = detector.detect_language

    def detect(**kwargs):
        result = original(**kwargs)
        if stage == "sampling":
            now[0] = 181.0
        return result

    def decode(*args, **kwargs):
        decodes.append(kwargs)
        now[0] = 181.0
        return iter([segment(-0.1)]), None

    detector.detect_language, detector.transcribe = detect, decode
    kwargs = {}
    with caplog.at_level(logging.INFO):
        assert t._apply_language_prior(task, detector, task.file_path, 600, cfg, kwargs, None) is None
    assert not kwargs and "reason=fallback" in caplog.text and "180 s deadline" in caplog.text
    assert len(detector.calls) == (1 if stage == "sampling" else 5)
    assert len(decodes) == (0 if stage == "sampling" else 1)


@pytest.mark.parametrize("stage", ["sampling", "verification", "iterator"])
def test_cancellation_aborts_before_main_decode_and_cleans_slice(wiring, monkeypatch, stage):
    t, task, cfg, reads = wiring
    task.clip_start, task.clip_end = 10, 290
    sliced = Path(task.file_path).with_name("slice.wav")
    sliced.write_bytes(b"fake slice")
    monkeypatch.setattr(t, "_slice_audio_from", lambda *args, **kwargs: str(sliced))
    detector = FakeDetector(REAL_TEN_MINUTES)
    original = detector.detect_language
    decodes = []

    def detect(**kwargs):
        result = original(**kwargs)
        if stage == "sampling":
            task.cancelled = True
        return result

    def transcribe(path, **kwargs):
        assert not isinstance(path, str), "Cancelled preflight must not start main decode"
        decodes.append(kwargs)
        if stage == "verification":
            task.cancelled = True
        def segments():
            if stage == "iterator":
                task.cancelled = True
            yield segment(-0.1)
        return segments(), None

    detector.detect_language, detector.transcribe = detect, transcribe
    monkeypatch.setattr(t, "MODEL", detector)
    reported, logs = [], []
    t.transcribe(task, log_cb=logs.append, language_cb=lambda *args: reported.append(args))
    assert task.cancelled and not reported and not sliced.exists()
    assert len(detector.calls) == (1 if stage == "sampling" else 5)
    assert len(decodes) == (0 if stage == "sampling" else 1)
    assert any("Task cancelled" in line for line in logs)


@pytest.mark.parametrize("known_duration", [20, 100, 0, None])
def test_real_input_duration_clamps_stale_estimate(wiring, monkeypatch, known_duration):
    t, task, cfg, reads = wiring
    def probe(path):
        if known_duration is None:
            raise RuntimeError("ffprobe unavailable")
        return known_duration
    monkeypatch.setattr(t, "get_duration", probe)
    detector = FakeDetector([{"en": 1.0}] * 5)
    kwargs = {}
    result = t._apply_language_prior(task, detector, task.file_path, 600, cfg, kwargs, None)
    assert result.language == "en"
    assert [(start, length) for path, start, length in reads] == prior.sample_windows(known_duration or 600)


def test_read_failures_are_skipped_in_wiring(wiring, monkeypatch, caplog):
    t, task, cfg, reads = wiring
    def read(path, start, length, **kwargs):
        reads.append(start)
        if start in (45, 525):
            raise RuntimeError("empty audio / ffmpeg error")
        return start
    monkeypatch.setattr(t, "get_duration", lambda path: 600)
    monkeypatch.setattr(t, "_read_language_window", read)
    model = FakeDetector([{"en": 1.0}] * 3)
    with caplog.at_level(logging.INFO):
        result = t._apply_language_prior(task, model, task.file_path, 600, cfg, {}, None)
    assert result.window_count == 3 and result.language == "en"
    assert len(reads) == 5 and "windows=3" in caplog.text
    assert len([r for r in caplog.records if "Skipping language window" in r.message]) == 2


def test_audio_reader_bounds_stderr_and_rejects_empty_audio(monkeypatch):
    from core import transcriber as t
    from io import BytesIO
    monkeypatch.setattr(t, "bundled_binary", lambda name: "ffmpeg")

    def process(command, **kwargs):
        return SimpleNamespace(stdout=BytesIO(), stderr=BytesIO(b"x" * 10000 + b"TAIL"),
                               wait=lambda **kw: 1, poll=lambda: 1, returncode=1, args=command)
    monkeypatch.setattr(t.subprocess, "Popen", process)
    with pytest.raises(RuntimeError) as error:
        t._read_language_window("bad.wav", 0, 30)
    assert str(error.value).endswith("x" * 2044 + "TAIL")
    assert len(str(error.value)) < 2150

    def empty(command, **kwargs):
        result = process(command, **kwargs)
        result.returncode = 0
        return result
    monkeypatch.setattr(t.subprocess, "Popen", empty)
    with pytest.raises(ValueError, match="no audio"):
        t._read_language_window("empty.wav", 0, 30)


@pytest.mark.parametrize("interrupt", ["timeout", "cancel"])
def test_audio_reader_kills_process_on_timeout_or_cancel(monkeypatch, interrupt):
    from core import transcriber as t
    from io import BytesIO
    killed = []
    def process(command, **kwargs):
        return SimpleNamespace(stdout=BytesIO(), stderr=BytesIO(), args=command,
                               poll=lambda: None if not killed else -9,
                               kill=lambda: killed.append(True), wait=lambda **kw: -9)
    monkeypatch.setattr(t, "bundled_binary", lambda name: "ffmpeg")
    monkeypatch.setattr(t.subprocess, "Popen", process)
    def check():
        if interrupt == "cancel":
            raise prior.PreflightCancelled()
    with pytest.raises(prior.PreflightCancelled if interrupt == "cancel" else t.subprocess.TimeoutExpired):
        t._read_language_window("talk.wav", 0, 30, timeout=0, check=check)
    assert killed == [True]


def test_real_media_reader_first_stream_and_short_clip(tmp_path, monkeypatch):
    """Use only the bundled ffmpeg, with no network or installed system fallback."""
    from core import transcriber as t
    import numpy as np
    ffmpeg = Path(__file__).resolve().parents[2] / "bin" / ("ffmpeg.exe" if t.os.name == "nt" else "ffmpeg")
    if not ffmpeg.is_file():
        pytest.skip("Bundled bin/ffmpeg is absent")
    monkeypatch.setattr(t, "bundled_binary", lambda name: str(ffmpeg))
    media = tmp_path / "two-tracks.mka"
    # Mark the SECOND stream as default to prove first-stream selection explicitly.
    t.subprocess.run(
        [str(ffmpeg), "-nostdin", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
         "-f", "lavfi", "-i", "sine=frequency=880:duration=2", "-map", "0:a", "-map", "1:a",
         "-c:a", "pcm_s16le", "-disposition:a:0", "0", "-disposition:a:1", "default", str(media)],
        stdin=t.subprocess.DEVNULL, capture_output=True, check=True, timeout=30, **t.new_session_kwargs())
    audio = t._read_language_window(str(media), 0.5, 30)
    assert 1.4 < len(audio) / 16000 < 1.6
    frequencies = np.fft.rfftfreq(len(audio), 1 / 16000)
    peak = frequencies[np.argmax(abs(np.fft.rfft(audio)))]
    assert peak == pytest.approx(440, abs=2)
    with pytest.raises(ValueError, match="no audio"):
        t._read_language_window(str(media), 3, 30)
