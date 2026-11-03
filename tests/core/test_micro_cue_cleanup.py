"""Recorded decoder micro-cues are collapsed after every final decode path."""
from __future__ import annotations

import copy
from pathlib import Path

import pytest

from core import loop_guard
from core.convert import parse_to_segments
from core.task import TranscriptionTask
from core.transcriber import _run_post_pipeline as real_post
from core.writers.srt import write as write_srt
from tests.core.test_loop_guard_transcriber import Engine, Seg, _wire, _write_prior_checkpoint, t  # noqa: F401


PHRASE = "Yes, it's one of my dreams. \u00bfViene de visita a Santiago?"


def lesson_burst():
    edges = [149.46, 149.54, 149.62, 149.70, 149.86, 149.94, 150.02]
    return [
        {"start": 140.22, "end": 149.46,
         "text": "\u00bfViene de visita a Santiago? " + PHRASE},
        *[{"start": a, "end": b, "text": PHRASE} for a, b in zip(edges, edges[1:])],
        {"start": 150.02, "end": 165., "text": "it's one of my dreams. S\u00ed, es uno de mis sue\u00f1os."},
    ]


def test_six_identical_micro_cues_between_normal_cues(t, monkeypatch):
    monkeypatch.setitem(t.config, "diarization_enabled", False)
    monkeypatch.setitem(t.config, "alignment", "none")
    monkeypatch.setitem(t.config, "auto_chapters_enabled", False)
    monkeypatch.setitem(t.config, "hallucination_detect_enabled", False)
    segments = lesson_burst()
    real_post(TranscriptionTask("unused.wav"), segments, "es", None)
    assert [s["text"] for s in segments] == [lesson_burst()[0]["text"], lesson_burst()[-1]["text"]]
    assert [(s["start"], s["end"]) for s in segments] == [(140.22, 149.46), (150.02, 165.)]


def test_standalone_run_covers_span_and_keeps_metadata():
    cues = lesson_burst()[1:-1]
    cues[0]["speaker"] = "A"
    for cue in cues[1:]:
        cue["speaker"] = "A"
    cues[0]["words"] = [{"start": 149.46, "end": 149.5, "word": "Yes"}]
    original = copy.deepcopy(cues)
    result = loop_guard.collapse_micro_cues(cues)
    assert len(result) == 1
    assert (result[0]["start"], result[0]["end"]) == (149.46, 150.02)
    assert result[0]["text"] == PHRASE and result[0]["speaker"] == "A"
    assert result[0]["words"] == cues[0]["words"]
    assert cues == original
    assert loop_guard.collapse_micro_cues(result) == result


def test_normal_repeats_short_words_speaker_changes_and_distant_cues_survive():
    cases = [
        [{"start": 0, "end": 2, "text": "Repeat after me."},
         {"start": 4, "end": 6, "text": "Repeat after me."}],
        [{"start": 0, "end": .08, "text": "Yes."}],
        [{"start": 0, "end": .08, "text": "Yes.", "speaker": "A"},
         {"start": .08, "end": .16, "text": "Yes.", "speaker": "B"}],
        [{"start": 0, "end": .08, "text": PHRASE},
         {"start": 4, "end": 4.08, "text": PHRASE}],
        [{"start": 0, "end": 2, "text": "This repeats inside. This repeats inside."}],
    ]
    for cues in cases:
        assert loop_guard.collapse_micro_cues(cues) == cues


def test_neighbour_match_requires_words_not_a_substring():
    cues = [{"start": 0, "end": 3, "text": "Yesterday."},
            {"start": 3, "end": 3.08, "text": "Yes."},
            {"start": 3.08, "end": 3.16, "text": "yes!"}]
    result = loop_guard.collapse_micro_cues(cues)
    assert len(result) == 2 and result[1]["text"] == "Yes."
    assert result[1]["end"] == 3.16


def test_zero_duration_words_survive_and_nonword_stubs_go():
    cues = [{"start": 0, "end": 0, "text": "..."},
            {"start": 0.5, "end": 0.5, "text": "real words"},
            {"start": 1, "end": 1.04, "text": "..."},
            {"start": 2, "end": 2.04, "text": "Yes."},
            {"start": 3, "end": 4, "text": "..."}]
    assert loop_guard.collapse_micro_cues(cues) == [cues[1], cues[3], cues[4]]


def test_identical_zero_duration_burst_keeps_one_copy():
    cues = [{"start": 5 + i * .1, "end": 5 + i * .1, "text": "Here you go."} for i in range(6)]
    assert [c["text"] for c in loop_guard.collapse_micro_cues(cues)] == ["Here you go."]


def test_unknown_or_reversed_times_are_not_a_reason_to_lose_unique_text():
    cues = [{"start": 4, "end": 3, "text": "Keep this text."},
            {"start": "unknown", "end": 5, "text": "Keep this too."}]
    assert loop_guard.collapse_micro_cues(cues) == cues


@pytest.mark.parametrize("mode", ["fresh", "batched", "rescue", "resume", "complete", "language", "mixed", "alternate"])
def test_every_completion_path_filters_micro_cues(t, monkeypatch, tmp_path, mode):
    audio = tmp_path / "lesson.wav"
    audio.write_bytes(b"audio")
    cues = lesson_burst()
    task = TranscriptionTask(str(audio))
    task.language = "es"
    if mode in {"resume", "complete"}:
        task = _write_prior_checkpoint(t, audio, cues if mode == "complete" else [], 0)
        if mode == "complete":
            import json
            from core import _checkpoint
            data = _checkpoint.load_checkpoint(str(audio))
            data["transcription_completed"] = True
            _checkpoint.checkpoint_path(str(audio)).write_text(json.dumps(data), encoding="utf-8")
    engine = Engine([Seg(s["start"], s["end"], s["text"]) for s in cues])
    _, written = _wire(t, monkeypatch, tmp_path, engine, batched=mode == "batched")
    monkeypatch.setattr(t, "_run_post_pipeline", real_post)
    monkeypatch.setitem(t.config, "diarization_enabled", False)
    monkeypatch.setitem(t.config, "alignment", "none")
    monkeypatch.setitem(t.config, "auto_chapters_enabled", False)
    monkeypatch.setitem(t.config, "hallucination_detect_enabled", False)
    monkeypatch.setattr(t, "_rescue_collapsed", lambda task, segs, *a, **k: cues if mode == "rescue" else segs)
    if mode == "language":
        slot = t._WhisperLanguageModel("fake/model", "fake")
        slot.model = engine
        monkeypatch.setattr(t._LM_RUNNER, "slot", slot, raising=False)
    if mode == "mixed":
        import types
        engine.model = types.SimpleNamespace()
        task.languages = ("en", "es")
    if mode == "alternate":
        from core.backends.base import LanguageInfo
        class Backend:
            def transcribe_to_segments(self, *a, **kw):
                return cues, LanguageInfo("es", .9)
        t._transcribe_via_alt_backend("whisper_cpp", task, None, None, None, backend=Backend())
    elif mode in {"resume", "complete"}:
        assert t.resume_transcription(task)
    else:
        t.transcribe(task)
    assert len(written["segs"]) == 2


def test_real_srt_outputs(tmp_path):
    paths = sorted((Path(__file__).resolve().parents[2] / "RESEARCH").glob("real-job*.srt"))
    if not paths:
        pytest.skip("Recorded SRT evidence is not distributed with the test suite")
    counts = {"real-job0.srt": (267, 267), "real-job1.srt": (178, 172), "real-job3.srt": (218, 217)}
    for path in paths:
        cues = parse_to_segments(str(path))
        original = copy.deepcopy(cues)
        result = loop_guard.collapse_micro_cues(cues)
        assert (len(cues), len(result)) == counts[path.name]
        if path.name == "real-job0.srt":
            assert result == cues
        assert cues == original
        assert loop_guard.collapse_micro_cues(result) == result
        assert [c["start"] for c in result] == sorted(c["start"] for c in result)
        output = tmp_path / path.name
        output.write_text(write_srt(result), encoding="utf-8")
        assert parse_to_segments(str(output)) == result


def test_micro_cue_properties():
    hypothesis = pytest.importorskip("hypothesis")
    from hypothesis import strategies as st

    @hypothesis.settings(max_examples=200, deadline=None, database=None, derandomize=True)
    @hypothesis.given(st.lists(st.tuples(st.integers(1, 2500), st.integers(0, 4000),
                                        st.sampled_from(["Alpha beta.", "Gamma.", "Yes!", "\u00bfHola?"])),
                              min_size=1, max_size=35))
    def check(rows):
        cursor, cues = 0, []
        for duration, gap, text in rows:
            cues.append({"start": cursor / 1000, "end": (cursor + duration) / 1000, "text": text})
            cursor += duration + gap
        original = copy.deepcopy(cues)
        result = loop_guard.collapse_micro_cues(cues)
        assert cues == original
        assert result == loop_guard.collapse_micro_cues(cues)
        assert result == loop_guard.collapse_micro_cues(result)
        assert {c["text"] for c in result} == {c["text"] for c in cues}
        assert all(c in result for c in cues if round(c["end"] - c["start"], 6) > .3)
        assert all(cues[0]["start"] <= c["start"] < c["end"] <= cues[-1]["end"] for c in result)
        assert all(a["end"] <= b["start"] for a, b in zip(result, result[1:]))

    check()
