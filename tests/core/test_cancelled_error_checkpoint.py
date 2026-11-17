"""Cancellation racing a decoder error must not lose accepted resume work."""
import json

import pytest

from core import _checkpoint as cp, transcriber as tr
from tests.core.test_transcription_endpoint_bounds import (
    Segment, endpoint_case, install_model, output_task,
)


def prepare(case, monkeypatch, resume):
    task = output_task(case)
    prior = [{"start": 0.0, "end": 1.0, "text": "prior"}] if resume else []
    if resume:
        tr._write_periodic_checkpoint(task, prior, 1.0, "en", 0.9, None)
    # The error must save work accepted since the last periodic write.
    monkeypatch.setattr(tr, "_CHECKPOINT_EVERY_N_SEGMENTS", 100000)
    monkeypatch.setattr(tr, "_CHECKPOINT_EVERY_N_SECONDS", float("inf"))
    sentinel = case.audio.with_suffix(".srt")
    sentinel.write_bytes(b"previous completed output")
    return task, prior, sentinel


def checkpoint(task):
    return cp.load_checkpoint(task.file_path)


def assert_prefix(case, task, prior, sentinel):
    saved = checkpoint(task)
    assert saved is not None, "Accepted work must have a resumable checkpoint"
    assert [row["text"] for row in saved["segments"]] == [row["text"] for row in prior] + ["valid"]
    assert saved["last_end_time"] == 1.5
    assert saved["transcription_completed"] is False
    assert sentinel.read_bytes() == b"previous completed output"
    assert not task.output_paths and case.writes == []


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("kind", ["timing", "decoder"])
@pytest.mark.parametrize("cancel", [False, True])
def test_error_keeps_latest_prefix_even_when_cancel_races(endpoint_case, monkeypatch, resume, kind, cancel):
    task, prior, sentinel = prepare(endpoint_case, monkeypatch, resume)
    offset = 1.0 if resume else 0.0
    real_keep = tr._keep_timing_recovery

    def keep_then_cancel(*args, **kwargs):
        path = real_keep(*args, **kwargs)
        task.cancelled = cancel
        return path

    monkeypatch.setattr(tr, "_keep_timing_recovery", keep_then_cancel)

    def decoded():
        yield Segment(1.1 - offset, 1.5 - offset, "valid", [])
        if kind == "decoder":
            task.cancelled = cancel
            raise RuntimeError("synthetic decoder error after accepted text")
        yield Segment(2.6 - offset, 2.5 - offset, "invalid", [])

    install_model(monkeypatch, decoded(), duration=endpoint_case.duration - offset)
    expected = tr._TimingBoundsError if kind == "timing" else RuntimeError
    with pytest.raises(expected):
        (tr.resume_transcription if resume else tr.transcribe)(task)
    assert task.cancelled is cancel
    assert_prefix(endpoint_case, task, prior, sentinel)
    if kind == "timing":
        records = [json.loads(path.read_text(encoding="utf-8"))
                   for path in cp.partials_dir().glob("*.timing-recovery.json")]
        assert any(row["segments"][-1]["text"] == "invalid" for row in records)


@pytest.mark.parametrize("resume", [False, True])
def test_ordinary_cancel_still_saves_the_same_prefix(endpoint_case, monkeypatch, resume):
    task, prior, sentinel = prepare(endpoint_case, monkeypatch, resume)
    offset = 1.0 if resume else 0.0

    def decoded():
        yield Segment(1.1 - offset, 1.5 - offset, "valid", [])
        task.cancelled = True
        yield Segment(2.0 - offset, 2.2 - offset, "not accepted", [])

    install_model(monkeypatch, decoded(), duration=endpoint_case.duration - offset)
    (tr.resume_transcription if resume else tr.transcribe)(task)
    assert_prefix(endpoint_case, task, prior, sentinel)


@pytest.mark.parametrize("resume", [False, True])
def test_failed_error_checkpoint_is_reported_without_replacing_old_work(endpoint_case, monkeypatch, resume):
    task, prior, sentinel = prepare(endpoint_case, monkeypatch, resume)
    before = cp.checkpoint_path(task.file_path).read_bytes() if resume else None
    offset = 1.0 if resume else 0.0
    logs = []

    def decoded():
        yield Segment(1.1 - offset, 1.5 - offset, "valid", [])
        task.cancelled = True
        raise RuntimeError("synthetic decoder error after accepted text")

    def refuse_write(*args, **kwargs):
        raise OSError("synthetic checkpoint storage refusal")

    install_model(monkeypatch, decoded(), duration=endpoint_case.duration - offset)
    monkeypatch.setattr(cp, "write_checkpoint", refuse_write)
    with pytest.raises(RuntimeError, match="synthetic decoder error"):
        (tr.resume_transcription if resume else tr.transcribe)(task, log_cb=logs.append)
    assert task.checkpoint_failures == 1
    assert any("could not write partial checkpoint" in line for line in logs)
    if resume:
        assert cp.checkpoint_path(task.file_path).read_bytes() == before
    else:
        assert checkpoint(task) is None
    assert sentinel.read_bytes() == b"previous completed output"
    assert not task.output_paths and endpoint_case.writes == []
