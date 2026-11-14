"""Optional posthoc alignment must preserve safe original word timings."""
from copy import deepcopy
from types import ModuleType, SimpleNamespace as NS
import sys

import pytest

from core import alignment as alignment
from core import transcriber as tr


def original_segments():
    return [
        {"start": 0.0, "end": 2.0, "text": "hello world", "words": [
            {"start": 0.0, "end": 1.0, "word": "hello"},
            {"start": 1.0, "end": 2.0, "word": "world"}]},
        {"start": 9.2, "end": 10.0, "text": "ok bye", "words": [
            {"start": 9.2, "end": 9.6, "word": "ok"},
            {"start": 10.0, "end": 10.0, "word": "bye"}]},
    ]


def install_aligner(monkeypatch, last):
    rows = [NS(words=[NS(word="hello", start=0.1, end=0.9, probability=1.0),
                      NS(word="world", start=1.1, end=1.9, probability=1.0)]),
            NS(words=[NS(word="ok", start=9.2, end=9.6, probability=1.0), last])]
    fake = ModuleType("stable_whisper")
    fake.WhisperResult = lambda payload: NS(language="en")
    fake.load_model = lambda _: NS(align=lambda *a, **kw: NS(segments=rows))
    monkeypatch.setitem(sys.modules, "stable_whisper", fake)
    monkeypatch.setattr(alignment, "is_available", lambda: True)


def word_for(case):
    fields = {"word": "bye", "start": 10.0, "end": 10.0, "probability": 1.0}
    if case == "missing-end":
        fields.pop("end")
        fields["start"] = 9.7
    elif case == "nan-start":
        fields["start"] = float("nan")
    elif case == "infinite-end":
        fields["end"] = float("inf")
    elif case == "negative-start":
        fields["start"] = -0.1
    elif case == "reversed":
        fields.update(start=9.9, end=9.8)
    elif case == "past-audio-end":
        fields.update(start=10.02, end=10.03)
    return NS(**fields)


@pytest.mark.parametrize("case", ["missing-end", "nan-start", "infinite-end", "negative-start", "reversed"])
def test_invalid_refinement_rejected_before_any_segment_mutates(monkeypatch, tmp_path, case):
    install_aligner(monkeypatch, word_for(case))
    audio = tmp_path / "fixture.wav"
    audio.write_bytes(b"stub; no audio decoder is used")
    segments = original_segments()
    before = deepcopy(segments)
    assert all(tr._cap_segment(s, 10.0) == s for s in segments)
    result = alignment.refine_word_timestamps_in_place(str(audio), segments)
    assert result is False, "text-matching malformed timings must be an atomic soft rejection"
    assert segments == before


@pytest.mark.parametrize("case", ["missing-end", "nan-start", "infinite-end", "negative-start", "reversed", "past-audio-end"])
def test_optional_post_pipeline_preserves_valid_eof_words(monkeypatch, tmp_path, case):
    install_aligner(monkeypatch, word_for(case))
    monkeypatch.setattr(tr, "config", {"alignment": "stable_ts", "diarization_enabled": False,
        "hallucination_detect_enabled": False, "auto_chapters_enabled": False})
    audio = tmp_path / "fixture.wav"
    audio.write_bytes(b"stub; no audio decoder is used")
    task = NS(file_path=str(audio), cancelled=False, whisper_task="transcribe", _audio_end=10.0)
    segments = original_segments()
    before = deepcopy(segments)
    tr._enforce_audio_end(task, segments)
    tr._run_post_pipeline(task, segments, "en", lambda _: None)
    tr._enforce_audio_end(task, segments)
    assert segments == before, "optional invalid alignment must not destroy the valid EOF token"


def test_exact_zero_length_eof_remains_valid_and_exportable(monkeypatch, tmp_path):
    install_aligner(monkeypatch, word_for("valid-eof"))
    audio = tmp_path / "fixture.wav"
    audio.write_bytes(b"stub; no audio decoder is used")
    segments = original_segments()
    assert alignment.refine_word_timestamps_in_place(str(audio), segments) is True
    assert segments[1]["words"][-1]["start"] == segments[1]["words"][-1]["end"] == 10.0
    assert tr._cap_segment(segments[1], 10.0) == segments[1]
    for fmt in ("srt", "vtt", "ass", "json"):
        rows = tr._segments_for_writer(segments, 10.0, fmt)
        assert "bye" in tr.get_writer(fmt)(rows, "source.wav")


@pytest.mark.parametrize("end", [10.0, 10.2], ids=["exact-eof", "end-clamped-only"])
def test_valid_post_pipeline_refinement_is_published(monkeypatch, tmp_path, end):
    last = word_for("valid-eof")
    if end > 10.0:
        last.start, last.end = 9.9, end
    install_aligner(monkeypatch, last)
    monkeypatch.setattr(tr, "config", {"alignment": "stable_ts", "diarization_enabled": False,
        "hallucination_detect_enabled": False, "auto_chapters_enabled": False})
    audio = tmp_path / "fixture.wav"
    audio.write_bytes(b"stub; no audio decoder is used")
    task = NS(file_path=str(audio), cancelled=False, whisper_task="transcribe", _audio_end=10.0)
    segments = original_segments()
    logs = []
    tr._run_post_pipeline(task, segments, "en", logs.append)
    tr._enforce_audio_end(task, segments)
    assert segments[0]["words"][0]["start"] == 0.1, "valid refinement must still replace ASR clocks"
    assert segments[-1]["words"][-1]["end"] == 10.0
    assert "Word alignment refined." in logs


@pytest.mark.parametrize("raises", [False, True], ids=["partial-false", "partial-raise"])
def test_review_partial_optional_mutation_is_isolated(monkeypatch, tmp_path, raises):
    monkeypatch.setattr(alignment, "is_available", lambda: True)
    def hostile(_path, rows, **kwargs):
        rows[0]["words"][0]["start"] = -30.0
        rows[0]["text"] = "corrupted copy"
        if raises:
            raise ValueError("synthetic aligner failure after mutation")
        return False
    monkeypatch.setattr(alignment, "refine_word_timestamps_in_place", hostile)
    monkeypatch.setattr(tr, "config", {"alignment": "stable_ts", "diarization_enabled": False,
        "hallucination_detect_enabled": False, "auto_chapters_enabled": False})
    task = NS(file_path=str(tmp_path / "audio.wav"), cancelled=False, whisper_task="transcribe", _audio_end=10.0)
    rows = original_segments(); before=deepcopy(rows)
    tr._run_post_pipeline(task, rows, "en", lambda _: None)
    assert rows == before


@pytest.mark.parametrize("extent", [None, 0, -1, float("nan"), float("inf")])
@pytest.mark.parametrize("cue_end", [10.0, 10.04], ids=["disjoint-cue", "compatible-cue"])
def test_review_unknown_extent_does_not_guess_or_clamp(monkeypatch, tmp_path, extent, cue_end):
    install_aligner(monkeypatch, word_for("past-audio-end"))
    monkeypatch.setattr(tr, "config", {"alignment": "stable_ts", "diarization_enabled": False,
        "hallucination_detect_enabled": False, "auto_chapters_enabled": False})
    audio=tmp_path / "fixture.wav";audio.write_bytes(b"fake")
    task=NS(file_path=str(audio),cancelled=False,whisper_task="transcribe",_audio_end=extent)
    rows=original_segments()
    rows[-1]["end"] = cue_end
    before = deepcopy(rows)
    tr._run_post_pipeline(task,rows,"en",lambda _:None)
    if cue_end == 10.0:
        # Media extent is unknown, but the optional words still cannot belong
        # wholly to a different known cue. Keep every original clock intact.
        assert rows == before
        tr._enforce_audio_end(task,rows)
        assert rows == before
        return
    assert rows[-1]["words"][-1]["start"] == 10.02
    assert rows[-1]["words"][-1]["end"] == 10.03
    tr._enforce_audio_end(task,rows)
    assert rows[-1]["words"][-1]["end"] == 10.03


def test_review_long_late_failure_preserves_every_original_clock(monkeypatch, tmp_path):
    monkeypatch.setattr(alignment,"is_available",lambda:True)
    def late_failure(_path, rows, **kwargs):
        for segment in rows:
            segment["words"][0]["start"] += 0.1
        rows[-1]["words"][0]["start"] = 10001.0
        rows[-1]["words"][0]["end"] = 10002.0
        return True
    monkeypatch.setattr(alignment,"refine_word_timestamps_in_place",late_failure)
    monkeypatch.setattr(tr,"config",{"alignment":"stable_ts","diarization_enabled":False,
        "hallucination_detect_enabled":False,"auto_chapters_enabled":False})
    rows=[{"start":i*2.0,"end":i*2.0+1.0,"text":f"word{i}",
        "words":[{"start":i*2.0,"end":i*2.0+1.0,"word":f"word{i}"}]} for i in range(5000)]
    before=deepcopy(rows)
    task=NS(file_path=str(tmp_path/"audio.wav"),cancelled=False,whisper_task="transcribe",_audio_end=10000.0)
    tr._run_post_pipeline(task,rows,"en",lambda _:None)
    tr._enforce_audio_end(task,rows)
    assert rows == before
