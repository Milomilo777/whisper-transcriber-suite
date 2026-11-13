"""Real persisted legacy timing failures resume only their verified valid prefix."""
from copy import deepcopy
import json
from pathlib import Path
import wave

import pytest

from core import _checkpoint as cp, transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (  # noqa: F401
    endpoint_case, output_task, install_model, Segment,
)


def seed(case, monkeypatch, *, completed=False, prefix=True, bad_word=False):
    with wave.open(str(case.audio), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(16000)
        out.writeframes(b"\0\0" * (600 * 16000))
    case.duration = 600.0
    monkeypatch.setattr(tr, "get_duration", lambda _p: 600.0)
    install_model(monkeypatch, [], duration=2.0)
    task = output_task(case)
    tr._remember_audio_end(task, str(case.audio))
    original = [{"start": 0.0, "end": 598.0, "text": "valid prefix", "words": []}] if prefix else []
    bad = {"start": 602.82, "end": 604.48, "text": "unplaced text", "words": []}
    if bad_word:
        bad = {"start": 598.0, "end": 600.0, "text": "unplaced text",
               "words": [{"start": 600.96, "end": 601.96, "word": "unplaced"}]}
    original.append(bad)
    tr._write_periodic_checkpoint(task, original, 604.48, "en", 0.9, None,
                                  transcription_completed=completed)
    path = cp.checkpoint_path(str(case.audio))
    assert json.loads(path.read_text(encoding="utf-8"))["audio_end"] == 600.0
    return original, path, path.read_bytes()


def records():
    return [json.loads(p.read_text(encoding="utf-8")) for p in cp.partials_dir().glob("*.timing-recovery.json")]


def install_tail(case, monkeypatch):
    sliced = []

    def slice_audio(source, start, directory):
        assert 0 <= start < 600.0
        sliced.append(start)
        target = Path(directory) / "repaired-tail.wav"
        with wave.open(str(source), "rb") as src:
            params = src.getparams()
            src.setpos(round(start * src.getframerate()))
            audio = src.readframes(src.getnframes() - src.tell())
        with wave.open(str(target), "wb") as dst:
            dst.setparams(params)
            dst.writeframes(audio)
        return str(target)

    monkeypatch.setattr(tr, "_slice_audio_from", slice_audio)
    install_model(monkeypatch, [Segment(0.1, 1.8, "decoded tail", [])], duration=2.0)
    return sliced


@pytest.mark.parametrize("completed", [False, True])
@pytest.mark.parametrize("bad_word", [False, True])
def test_poisoned_checkpoint_resumes_valid_tail_and_keeps_all_raw_text(endpoint_case, monkeypatch, completed, bad_word):
    case = endpoint_case
    original, path, _before = seed(case, monkeypatch, completed=completed, bad_word=bad_word)
    sliced = install_tail(case, monkeypatch)
    task = output_task(case)
    assert tr.resume_transcription(task) is True
    assert sliced == [598.0], "A poisoned cursor must never reach the slicer"
    assert [s["text"] for s in case.writes[-1]] == ["valid prefix", "decoded tail"]
    assert case.writes[-1][0] == original[0]
    assert case.writes[-1][-1]["start"] == pytest.approx(598.1)
    assert all(0 <= s["start"] <= s["end"] <= 600 for s in case.writes[-1])
    assert len(task.output_paths) == 3 and not path.exists()
    assert records()[-1]["segments"] == original


@pytest.mark.parametrize("completed", [False, True])
def test_recovery_storage_failure_keeps_original_checkpoint_and_outputs(endpoint_case, monkeypatch, completed):
    case = endpoint_case
    _original, path, before = seed(case, monkeypatch, completed=completed)
    sentinel = case.audio.with_suffix(".srt")
    sentinel.write_text("existing output", encoding="utf-8")

    def fail(*_a, **_k):
        raise OSError("synthetic recovery disk full")

    monkeypatch.setattr(tr, "_keep_timing_recovery", fail)
    with pytest.raises(OSError, match="recovery disk full"):
        tr.resume_transcription(output_task(case))
    assert path.read_bytes() == before
    assert sentinel.read_text(encoding="utf-8") == "existing output"
    assert case.writes == []


@pytest.mark.parametrize("completed", [False, True])
def test_no_valid_prefix_keeps_the_original_aside_for_a_fresh_run(endpoint_case, monkeypatch, completed):
    case = endpoint_case
    original, path, before = seed(case, monkeypatch, completed=completed, prefix=False)
    assert tr.resume_transcription(output_task(case)) is False
    kept = list(path.parent.glob(path.name + ".unverified-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == before
    assert not path.exists() and not case.writes
    assert records()[-1]["segments"] == original


def test_repaired_complete_checkpoint_rechecks_decoder_compatibility(endpoint_case, monkeypatch):
    case = endpoint_case
    tr.config["device"] = "cuda"
    original, path, before = seed(case, monkeypatch, completed=True)
    tr.config["device"] = "cpu"
    assert tr.resume_transcription(output_task(case)) is False
    kept = list(path.parent.glob(path.name + ".unverified-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == before
    assert records()[-1]["segments"] == original
    assert not case.writes


@pytest.mark.parametrize("completed", [False, True])
def test_no_tail_never_promotes_a_repaired_checkpoint_to_complete(endpoint_case, monkeypatch, completed):
    case = endpoint_case
    original, path, _ = seed(case, monkeypatch, completed=completed)
    original[0]["end"] = 600.0
    tr._write_periodic_checkpoint(output_task(case), original, 604.48, "en", 0.9, None,
                                  transcription_completed=completed)
    before = path.read_bytes()
    assert tr.resume_transcription(output_task(case)) is False
    kept = list(path.parent.glob(path.name + ".unverified-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == before
    assert not case.writes and records()[-1]["segments"] == original


def test_unsupported_backend_does_not_decode_a_repaired_complete_checkpoint(endpoint_case, monkeypatch):
    case = endpoint_case
    tr.config["transcribe_backend"] = "cloud_stt"
    original, path, before = seed(case, monkeypatch, completed=True)
    assert tr.resume_transcription(output_task(case)) is False
    kept = list(path.parent.glob(path.name + ".unverified-*"))
    assert len(kept) == 1 and kept[0].read_bytes() == before
    assert not case.writes and records()[-1]["segments"] == original


@pytest.mark.parametrize("end", [None, 0, -1, float("nan"), True])
def test_unknown_extent_does_not_attempt_checkpoint_timing_repair(monkeypatch, end):
    from types import SimpleNamespace
    task = SimpleNamespace(file_path="synthetic.wav", _audio_end=end)
    data = {"segments": [{"start": 99, "end": 100, "text": "kept"}]}
    def refuse(*_a, **_k):
        raise AssertionError("An unknown extent cannot justify timing repair")
    monkeypatch.setattr(tr, "_keep_timing_recovery", refuse)
    result, repaired = tr._recover_checkpoint_timing(task, data, None)
    assert result is data and repaired is False


def test_timing_repair_preserves_all_raw_fields_for_generated_prefixes(monkeypatch):
    import random
    from types import SimpleNamespace
    randomizer = random.Random(20261113)
    task = SimpleNamespace(file_path="synthetic.wav", _audio_end=20.0)
    kept = []
    monkeypatch.setattr(tr, "_keep_timing_recovery", lambda _path, values, _why: kept.append(deepcopy(values)) or "synthetic-recovery.json")
    for _ in range(64):
        count = randomizer.randrange(7)
        def text():
            samples = ["alpha", chr(10), "'quoted'", chr(0x641)+chr(0x627), chr(0xD800)]
            return ''.join(randomizer.choices(samples, k=3))
        prefix = [{"start": float(i*2), "end": float(i*2+1), "text": text(), "words": [],
                   "extra": {"index": i, "labels": [text(), None, True]}} for i in range(count)]
        invalid = {"start": 21.0, "end": 22.0, "text": text(), "words": []}
        suffix = [{"start": randomizer.random()*30, "end": 31.0, "text": text(), "raw": [text()]}
                  for _ in range(randomizer.randrange(4))]
        data = {"segments": prefix+[invalid]+suffix, "last_end_time": 31.0,
                "transcription_completed": randomizer.choice([False, True])}
        original = deepcopy(data)
        recovered, repaired = tr._recover_checkpoint_timing(task, data, None)
        assert repaired is True and data == original
        assert recovered["segments"] == prefix
        assert recovered["segment_count"] == count
        assert recovered["last_end_time"] == (float(count*2-1) if count else 0.0)
        assert recovered["transcription_completed"] is False
        assert kept[-1] == original["segments"]


@pytest.mark.parametrize("malformed", [[], "", [["start", 599.0], ["end", 600.0]]])
@pytest.mark.parametrize("completed", [False, True])
def test_malformed_word_shape_keeps_raw_data_and_recovers_prefix(endpoint_case, monkeypatch, malformed, completed):
    case = endpoint_case
    original, _path, _before = seed(case, monkeypatch, bad_word=True, completed=completed)
    original[-1]["words"] = [malformed]
    writer = output_task(case)
    tr._remember_audio_end(writer, str(case.audio))
    tr._write_periodic_checkpoint(writer, original, 604.48, "en", 0.9, None,
                                  transcription_completed=completed)
    sliced = install_tail(case, monkeypatch)
    assert tr.resume_transcription(output_task(case)) is True
    assert sliced == [598.0]
    assert [s["text"] for s in case.writes[-1]] == ["valid prefix", "decoded tail"]
    assert records()[-1]["segments"] == original



def test_unplaced_surrogate_text_round_trips_in_durable_recovery(endpoint_case, monkeypatch):
    case = endpoint_case
    original, _path, _before = seed(case, monkeypatch)
    original[-1]["text"] = "unplaced " + chr(0xD800)
    writer = output_task(case)
    tr._remember_audio_end(writer, str(case.audio))
    tr._write_periodic_checkpoint(writer, original, 604.48, "en", 0.9, None)
    sliced = install_tail(case, monkeypatch)
    assert tr.resume_transcription(output_task(case)) is True
    assert sliced == [598.0] and records()[-1]["segments"] == original


@pytest.mark.parametrize("completed", [False, True])
def test_cursor_only_overshoot_respects_completed_transcription(endpoint_case, monkeypatch, completed):
    case = endpoint_case
    original, _path, _before = seed(case, monkeypatch, completed=completed)
    original = original[:1]
    writer = output_task(case)
    tr._remember_audio_end(writer, str(case.audio))
    tr._write_periodic_checkpoint(writer, original, 604.48, "en", 0.9, None,
                                  transcription_completed=completed)
    if completed:
        def refuse(*_a, **_k):
            raise AssertionError("A valid complete transcript does not need another decode")
        monkeypatch.setattr(tr, "_slice_audio_from", refuse)
        monkeypatch.setattr(tr, "_whisper_runner", refuse)
    else:
        sliced = install_tail(case, monkeypatch)
    task = output_task(case)
    assert tr.resume_transcription(task) is True
    if completed:
        assert case.writes[-1] == original and not records()
    else:
        assert sliced == [598.0]
        assert [s["text"] for s in case.writes[-1]] == ["valid prefix", "decoded tail"]
        assert records()[-1]["segments"] == original
