"""Padding hallucinations preserve raw evidence without discarding valid output."""
import json
from copy import deepcopy
from pathlib import Path

import pytest

from core import _checkpoint as cp, transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (
    Segment, endpoint_case, install_model, output_task,
)


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("batched", [False, True])
def test_half_second_late_cue_finishes_with_outputs(endpoint_case, monkeypatch, resume, batched):
    case = endpoint_case
    task = output_task(case)
    if batched:
        tr.config.update(batch_size=2, vad_filter=True)
        monkeypatch.setattr(tr, "device", "cuda")
        monkeypatch.setattr(tr, "_EFFECTIVE_DEVICE", "cuda")
        monkeypatch.setattr(tr, "PIPELINE", tr.MODEL)
    offset = 1.0 if resume else 0.0
    if resume:
        tr._write_periodic_checkpoint(task, [{"start": 0, "end": 1, "text": "prior"}], 1, "en", .9, None)
    checkpoints = []
    save = tr._write_periodic_checkpoint
    def checkpoint(task, rows, *args, **kwargs):
        checkpoints.append(deepcopy(rows))
        return save(task, rows, *args, **kwargs)
    monkeypatch.setattr(tr, "_write_periodic_checkpoint", checkpoint)
    install_model(monkeypatch, [Segment(1.1-offset, 1.5-offset, "valid", []),
                               Segment(case.duration+.5-offset, case.duration+1-offset, "invented", [])],
                  duration=case.duration-offset)
    logs = []
    (tr.resume_transcription if resume else tr.transcribe)(task, log_cb=logs.append)
    assert len(task.output_paths) == 3
    assert all(Path(p).is_file() and "invented" not in Path(p).read_text(encoding="utf-8")
               for p in task.output_paths)
    assert [s["text"] for s in case.writes[-1]] == (["prior", "valid"] if resume else ["valid"])
    records = list(cp.partials_dir().glob("*.timing-recovery.json"))
    assert any(json.loads(p.read_text(encoding="utf-8"))["segments"][-1]["text"] == "invented" for p in records)
    warnings = [line for line in logs if "dropped" in line.lower()]
    assert len(warnings) == 1 and "1" in warnings[0]
    assert any(str(p) in warnings[0] for p in records)
    assert not cp.checkpoint_path(task.file_path).exists()
    assert checkpoints and all(all(s["text"] != "invented" for s in rows) for rows in checkpoints)


@pytest.mark.parametrize("completed", [False, True])
def test_checkpoint_drops_tail_without_losing_valid_suffix(endpoint_case, monkeypatch, completed):
    task = output_task(endpoint_case)
    raw = [{"start": 0, "end": 1, "text": "valid"},
           {"start": 2.988, "end": 3.4, "text": "invented"},
           {"start": 1.1, "end": 1.5, "text": "following valid"}]
    tr._write_periodic_checkpoint(task, raw, 3.4, "en", .9, None,
                                  transcription_completed=completed)
    install_model(monkeypatch, [], duration=endpoint_case.duration-1.5)
    assert tr.resume_transcription(task)
    assert len(task.output_paths) == 3
    assert [s["text"] for s in endpoint_case.writes[-1]] == ["valid", "following valid"]
    records = list(cp.partials_dir().glob("*.timing-recovery.json"))
    assert json.loads(records[-1].read_text(encoding="utf-8"))["segments"] == raw


@pytest.mark.parametrize("phase", ["rescue", "post"])
def test_recheck_drops_tail_and_finishes(endpoint_case, monkeypatch, phase):
    task = output_task(endpoint_case)
    install_model(monkeypatch, [Segment(.2, 1.5, "valid", [])])
    raw = {"start": 2.988, "end": 3.4, "text": "invented", "words": []}
    def inject(task, rows, *args, **kwargs):
        rows.append(raw)
        return rows if phase == "rescue" else 0
    monkeypatch.setattr(tr, "_rescue_collapsed" if phase == "rescue" else "_run_post_pipeline", inject)
    logs = []
    tr.transcribe(task, log_cb=logs.append)
    assert len(task.output_paths) == 3
    assert [s["text"] for s in endpoint_case.writes[-1]] == ["valid"]
    records = list(cp.partials_dir().glob("*.timing-recovery.json"))
    assert json.loads(records[-1].read_text(encoding="utf-8"))["segments"][-1] == raw
    warnings = [line for line in logs if "dropped" in line.lower()]
    assert len(warnings) == 1 and "1 cue(s)" in warnings[0]
    assert str(records[-1]) in warnings[0]


@pytest.mark.parametrize("fmt", tr.supported_formats())
def test_writer_drops_late_cue_and_keeps_raw(endpoint_case, fmt):
    raw = [{"start": 0, "end": 1, "text": "valid"},
           {"start": 2.988, "end": 3.4, "text": "invented"}]
    assert tr._segments_for_writer(raw, endpoint_case.duration, fmt) == raw[:1]
    record = next(cp.partials_dir().glob("*.timing-recovery.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["segments"] == raw


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -1, 4.0])
@pytest.mark.parametrize("word", [False, True])
def test_corrupt_timing_in_padding_still_fails(endpoint_case, bad, word):
    task = output_task(endpoint_case)
    task._audio_end = endpoint_case.duration
    raw = {"start": 3, "end": 3.4, "text": "fault", "words": []}
    target = {"start": bad, "end": 3.4, "word": "fault"}
    if word:
        raw["words"] = [target]
    else:
        raw["start"] = bad
    with pytest.raises(tr._TimingBoundsError):
        tr._enforce_audio_end(task, [raw])
    record = next(cp.partials_dir().glob("*.timing-recovery.json"))
    assert json.loads(record.read_text(encoding="utf-8"))["segments"][0]["text"] == "fault"


@pytest.mark.parametrize("text,token,expected", [
    ("Hello! ghost", "Hello", "Hello!"),
    ("“Hello” ghost", "Hello", "“Hello”"),
    ("你好，ghost", "你好", "你好，"),
    ("Hello! ghost", "Hello!", "Hello!"),
])
def test_dropped_word_keeps_valid_punctuation(endpoint_case, monkeypatch, text, token, expected):
    from tests.core.test_transcription_endpoint_bounds import Word
    case = endpoint_case
    task = output_task(case)
    install_model(monkeypatch, [Segment(.1, 3.5, text, [
        Word(.1, 1, token), Word(case.duration, 3.5, "ghost"),
    ])])
    tr.transcribe(task)
    assert len(task.output_paths) == 3
    assert case.writes[-1][0]["text"] == expected
    assert [w["word"] for w in case.writes[-1][0]["words"]] == [token]
    records = list(cp.partials_dir().glob("*.timing-recovery.json"))
    assert json.loads(records[-1].read_text(encoding="utf-8"))["segments"][0]["text"] == text
