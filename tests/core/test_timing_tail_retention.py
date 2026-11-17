"""Rejected clocks must not silently drop the lazy decoder's following text."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import _checkpoint as cp, transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (
    Segment, Word, endpoint_case, install_model, output_task,
)


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("tail_error", [False, True])
def test_lazy_text_after_rejected_clock_is_kept_without_advancing_prefix(endpoint_case, monkeypatch, resume, tail_error):
    task = output_task(endpoint_case)
    offset = 1.0 if resume else 0.0
    prior = [{"start": 0, "end": 1, "text": "prior"}] if resume else []
    if resume:
        tr._write_periodic_checkpoint(task, prior, 1.0, "en", 0.9, None)
    calls = []
    def decoded():
        for start, end, text in [(1.1, 1.5, "valid"), (2.6, 2.5, "rejected"),
                                  (2.8, 3.2, "later text")]:
            calls.append(text)
            if text == "later text":
                # Raw evidence is durable before the extra lazy decoder step.
                saved = [json.loads(path.read_text(encoding="utf-8"))
                         for path in cp.partials_dir().glob("*.timing-recovery.json")]
                assert any(record["segments"][-1]["text"] == "rejected" for record in saved)
            yield Segment(start-offset, end-offset, text, [Word(start-offset, end-offset)])
        if tail_error:
            raise RuntimeError("synthetic decoder failure after yielded text")
    install_model(monkeypatch, decoded(), duration=endpoint_case.duration-offset)
    with pytest.raises(tr._TimingBoundsError):
        (tr.resume_transcription if resume else tr.transcribe)(task)
    records = [json.loads(path.read_text(encoding="utf-8"))
               for path in cp.partials_dir().glob("*.timing-recovery.json")]
    complete = max(records, key=lambda record: len(record["segments"]))
    assert [segment["text"] for segment in complete["segments"]] == (
        ["prior", "valid", "rejected", "later text"] if resume else ["valid", "rejected", "later text"])
    assert complete["segments"][-1]["start"] == 2.8
    assert complete["segments"][-1]["end"] == 3.2
    assert complete["segments"][-1]["words"][0]["start"] == 2.8
    assert ("decoder-error:RuntimeError" if tail_error else "exhausted") in complete["reason"]
    assert calls == ["valid", "rejected", "later text"]
    checkpoint = json.loads(cp.checkpoint_path(task.file_path).read_text(encoding="utf-8"))
    assert checkpoint["last_end_time"] == 1.5
    assert [segment["text"] for segment in checkpoint["segments"]] == (["prior", "valid"] if resume else ["valid"])
    assert checkpoint["transcription_completed"] is False
    assert not task.output_paths and endpoint_case.writes == []


def capture(case, remaining, convert=lambda value: value):
    original = [{"start": 2.6, "end": 2.5, "text": "rejected"}]
    kept, stopped = tr._capture_timing_tail(output_task(case), original, remaining, convert, "bad timing")
    assert original == [{"start": 2.6, "end": 2.5, "text": "rejected"}]
    record = json.loads(Path(kept).read_text(encoding="utf-8")) if kept else None
    return record, stopped


@pytest.mark.parametrize("flag", ["cancelled", "paused"])
def test_cancel_or_pause_does_not_advance_remaining_decoder(endpoint_case, flag):
    task = output_task(endpoint_case)
    setattr(task, flag, True)
    def refuse():
        pytest.fail("Stopped task must not advance decoder")
        yield
    kept, stopped = tr._capture_timing_tail(task, [], refuse(), dict, "bad timing")
    assert stopped == flag
    assert kept is None
    assert not list(cp.partials_dir().glob("*.timing-recovery.json"))


def test_segment_budget_bounds_remaining_decoder_steps(endpoint_case, monkeypatch):
    monkeypatch.setattr(tr, "_TIMING_TAIL_SEGMENTS", 2)
    observed = []
    def remaining():
        for n in range(10):
            observed.append(n)
            yield {"text": f"extra {n}"}
    record, stopped = capture(endpoint_case, remaining())
    assert stopped == "segment-limit" and observed == [0, 1]
    assert [row["text"] for row in record["segments"]] == ["rejected", "extra 0", "extra 1"]


def test_loop_guard_ticks_count_against_step_budget(endpoint_case, monkeypatch):
    monkeypatch.setattr(tr, "_TIMING_TAIL_SEGMENTS", 2)
    observed = []
    def remaining():
        for n in range(10):
            observed.append(n)
            yield tr._loop_guard.LoopGuardTick(end=float(n))
    record, stopped = capture(endpoint_case, remaining(), lambda value: pytest.fail("Tick is not transcript text"))
    assert stopped == "segment-limit" and observed == [0, 1]
    assert record is None


def test_elapsed_budget_stops_between_decoder_steps(endpoint_case, monkeypatch):
    ticks = iter([0.0, 0.0, 3.0])
    monkeypatch.setattr(tr, "time", SimpleNamespace(monotonic=lambda: next(ticks)))
    remaining = iter([{"text": "first extra"}, {"text": "unread"}])
    record, stopped = capture(endpoint_case, remaining)
    assert stopped == "time-limit"
    assert [row["text"] for row in record["segments"]] == ["rejected", "first extra"]
    assert next(remaining) == {"text": "unread"}


def test_text_budget_preserves_whole_last_yield_before_stopping(endpoint_case, monkeypatch):
    monkeypatch.setattr(tr, "_TIMING_TAIL_TEXT_CHARS", 3)
    remaining = iter([{"text": "full extra text"}, {"text": "unread"}])
    record, stopped = capture(endpoint_case, remaining)
    assert stopped == "text-limit"
    assert record["segments"][-1]["text"] == "full extra text"
    assert next(remaining) == {"text": "unread"}


def test_conversion_failure_keeps_available_text_without_inventing_clocks(endpoint_case):
    def broken(value):
        raise ValueError("synthetic conversion error")
    record, stopped = capture(endpoint_case, iter([SimpleNamespace(text="retained text")]), broken)
    assert stopped == "conversion-error:ValueError"
    assert record["segments"][-1] == {"text": "retained text", "timing_unavailable": True}


@pytest.mark.parametrize("failing_write", [1, 2])
def test_storage_failure_never_claims_completion_or_changes_published_output(endpoint_case, monkeypatch, failing_write):
    task = output_task(endpoint_case)
    output = endpoint_case.audio.with_suffix(".srt")
    output.write_bytes(b"previous completed output")
    writes = []
    keep = tr._keep_timing_recovery
    def fail(source, segments, reason):
        writes.append(len(segments))
        if len(writes) == failing_write:
            raise OSError("synthetic recovery storage refusal")
        return keep(source, segments, reason)
    monkeypatch.setattr(tr, "_keep_timing_recovery", fail)
    observed = []
    def decoded():
        for start, end, text in [(1.1, 1.5, "valid"), (2.6, 2.5, "rejected"), (2.8, 3.2, "later")]:
            observed.append(text)
            yield Segment(start, end, text, [])
    install_model(monkeypatch, decoded(), duration=endpoint_case.duration)
    with pytest.raises(OSError, match="storage refusal"):
        tr.transcribe(task)
    assert observed == (["valid", "rejected"] if failing_write == 1 else ["valid", "rejected", "later"])
    assert output.read_bytes() == b"previous completed output"
    assert not task.output_paths and not endpoint_case.writes
    checkpoint = json.loads(cp.checkpoint_path(task.file_path).read_text(encoding="utf-8"))
    assert checkpoint["last_end_time"] == 1.5 and not checkpoint["transcription_completed"]
