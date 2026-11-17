"""A failed run must not start recovery decodes or obscure saved raw text."""
import errno
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from core import _checkpoint as cp, loop_guard, transcriber as tr
from core.backends.faster_whisper_be import WhisperDecode
from tests.core.test_transcription_endpoint_bounds import (
    Segment, endpoint_case, install_model, output_task,
)


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("error_number", [None, errno.ENOSPC, errno.EACCES])
@pytest.mark.parametrize("message", ["synthetic refusal", None])
def test_tail_storage_failure_names_existing_record_and_keeps_os_identity(
    endpoint_case, monkeypatch, resume, error_number, message,
):
    task = output_task(endpoint_case)
    offset = 1.0 if resume else 0.0
    if resume:
        tr._write_periodic_checkpoint(task, [{"start": 0, "end": 1, "text": "prior"}], 1, "en", .9, None)
    error = (OSError(message) if error_number is None
             else OSError(error_number, message))
    keep = tr._keep_timing_recovery
    paths = []
    def save(source, segments, reason):
        if paths:
            raise error
        path = keep(source, segments, reason)
        paths.append(path)
        return path
    monkeypatch.setattr(tr, "_keep_timing_recovery", save)
    segments = [Segment(s-offset, e-offset, t, []) for s, e, t in
                [(1.1, 1.5, "valid"), (2.6, 2.5, "rejected"), (2.8, 3.2, "later")]]
    install_model(monkeypatch, iter(segments), duration=endpoint_case.duration-offset)
    with pytest.raises(OSError) as caught:
        (tr.resume_transcription if resume else tr.transcribe)(task)
    assert caught.value is error
    assert error.errno == error_number
    assert paths[0] in str(error)
    assert (message is None or message in str(error)) and "timing" in str(error).lower()
    assert json.loads(cp.checkpoint_path(task.file_path).read_text(encoding="utf-8"))["last_end_time"] == 1.5
    assert len(list(cp.partials_dir().glob("*.timing-recovery.json"))) == 1
    assert not task.output_paths and not endpoint_case.writes


@pytest.mark.parametrize("stop", ["cancelled", "paused", "time-limit", "decoder-error", "segment-limit"])
def test_zero_extra_cues_do_not_duplicate_transcript(endpoint_case, monkeypatch, stop):
    task = output_task(endpoint_case)
    if stop in {"cancelled", "paused"}:
        setattr(task, stop, True)
    if stop == "time-limit":
        monkeypatch.setattr(tr, "_TIMING_TAIL_SECONDS", 0)
    if stop == "segment-limit":
        monkeypatch.setattr(tr, "_TIMING_TAIL_SEGMENTS", 0)
    def remaining():
        raise RuntimeError("decoder refused")
        yield
    original = [{"text": "retained " * 10000}]
    kept, reason = tr._capture_timing_tail(task, original, remaining(), dict, "timing")
    assert kept is None
    assert reason.startswith(stop)
    assert not list(cp.partials_dir().glob("*.timing-recovery.json"))


def test_capture_never_restarts_loop_guard_or_drops_following_repeats(endpoint_case):
    task = output_task(endpoint_case)
    task._audio_end = 2.0
    active = SimpleNamespace(retry_enabled=True)
    restarts = []
    raw = [Segment(2.6+n*.2, 2.7+n*.2, "repeat", []) for n in range(12)]
    guarded = loop_guard.guard_repeats(
        iter(raw), limit=3, hard=8, ticks=True,
        restart=lambda at: restarts.append(at) or iter([]),
        passthrough=lambda: not active.retry_enabled,
    )
    rejected = next(guarded)
    with pytest.raises(tr._TimingBoundsError):
        tr._enforce_decoded_audio_end(
            task, [{"start": rejected.start, "end": rejected.start - .1, "text": rejected.text}],
            recovery=lambda: [{"start": rejected.start, "end": rejected.start - .1, "text": rejected.text}],
            remaining=guarded,
            convert=lambda seg: {"start": seg.start, "end": seg.end, "text": seg.text},
            runner=active,
        )
    assert restarts == []
    records = [json.loads(p.read_text(encoding="utf-8")) for p in cp.partials_dir().glob("*.timing-recovery.json")]
    assert max(len(r["segments"]) for r in records) == 12
    assert active.retry_enabled is True


def test_capture_cuda_error_does_not_retry_or_change_device(endpoint_case):
    task = output_task(endpoint_case)
    task._audio_end = 2.0
    calls = []
    def decoded():
        yield Segment(2.6, 2.5, "rejected", [])
        raise RuntimeError("CUDA failed with error out of memory")
    backend = SimpleNamespace(transcribe=lambda *a, **kw: (decoded(), SimpleNamespace(language="en")))
    runner = WhisperDecode(lambda options: backend, lambda: True,
                           lambda *args: calls.append("recover"), None)
    runner.before_retry = lambda: calls.append("checkpoint")
    remaining, _ = runner.transcribe("unused.wav")
    next(remaining)
    raw = [{"start": 2.6, "end": 2.5, "text": "rejected"}]
    with pytest.raises(tr._TimingBoundsError, match="decoder-error:RuntimeError"):
        tr._enforce_decoded_audio_end(task, list(raw), recovery=lambda: raw,
                                     remaining=remaining, convert=dict, runner=runner)
    assert calls == []
    assert runner.retry_enabled is True


def test_disabled_retry_does_not_enter_recover_on_lazy_cuda_error():
    def decoded():
        yield SimpleNamespace(end=0)
        raise RuntimeError("CUDA failed with error out of memory")
    backend = SimpleNamespace(transcribe=lambda *a, **kw: (decoded(), SimpleNamespace()))
    calls = []
    def refuse_retry(*args):
        calls.append("recover")
        raise AssertionError("failed capture must not recover")
    runner = WhisperDecode(lambda options: backend, lambda: True, refuse_retry, None)
    remaining, _ = runner.transcribe("unused.wav")
    next(remaining)
    runner.retry_enabled = False
    with pytest.raises(RuntimeError, match="CUDA"):
        next(remaining)
    assert calls == []


def test_repeat_tail_baseline_demonstrates_restart_work():
    restarts = []
    raw = [Segment(2.6+n*.2, 2.7+n*.2, "repeat", []) for n in range(12)]
    guarded = loop_guard.guard_repeats(iter(raw), limit=3, hard=8, ticks=True,
                                     restart=lambda at: restarts.append(at) or iter([]))
    next(guarded)
    list(guarded)
    # Characterise the ordinary guard; recovery must bypass this work.
    assert len(restarts) == 1


@pytest.mark.parametrize("resume", [False, True])
@pytest.mark.parametrize("batched", [False, True])
def test_actual_caller_disables_lazy_cuda_recovery(endpoint_case, monkeypatch, resume, batched):
    task = output_task(endpoint_case)
    if batched:
        tr.config.update(batch_size=2, vad_filter=True)
    offset = 1.0 if resume else 0.0
    if resume:
        tr._write_periodic_checkpoint(task, [{"start": 0, "end": 1, "text": "prior"}], 1, "en", .9, None)
    def decoded():
        yield Segment(1.1-offset, 1.5-offset, "valid", [])
        yield Segment(2.6-offset, 2.5-offset, "rejected", [])
        raise RuntimeError("CUDA failed with error out of memory")
    install_model(monkeypatch, decoded(), duration=endpoint_case.duration-offset)
    monkeypatch.setattr(tr, "device", "cuda")
    monkeypatch.setattr(tr, "_EFFECTIVE_DEVICE", "cuda")
    if batched:
        monkeypatch.setattr(tr, "PIPELINE", tr.MODEL)
    create_runner = tr._whisper_runner
    retries = []
    runners = []
    def create(*args, **kwargs):
        runner = create_runner(*args, **kwargs)
        runners.append((runner, kwargs.get("batched")))
        def refuse(*args):
            retries.append("recover")
            raise AssertionError("must not change device after timing failure")
        runner._recover = refuse
        return runner
    monkeypatch.setattr(tr, "_whisper_runner", create)
    with pytest.raises(tr._TimingBoundsError, match="decoder-error:RuntimeError"):
        (tr.resume_transcription if resume else tr.transcribe)(task)
    assert retries == []
    assert runners[-1][1] is batched
    assert runners[-1][0].retry_enabled is True
    checkpoint = json.loads(cp.checkpoint_path(task.file_path).read_text(encoding="utf-8"))
    assert checkpoint["last_end_time"] == 1.5 and not checkpoint["transcription_completed"]
    assert not task.output_paths and not endpoint_case.writes


@pytest.mark.parametrize("resume", [False, True])
def test_actual_caller_keeps_guarded_repeated_raw_tail(endpoint_case, monkeypatch, resume):
    task = output_task(endpoint_case)
    tr.config["loop_guard_repeats"] = 3
    offset = 1.0 if resume else 0.0
    if resume:
        tr._write_periodic_checkpoint(task, [{"start": 0, "end": 1, "text": "prior"}], 1, "en", .9, None)
    raw = [Segment(2.6+n*.2-offset, 2.7+n*.2-offset, "repeat", []) for n in range(12)]
    install_model(monkeypatch, iter([Segment(1.1-offset, 1.5-offset, "valid", [])] + raw), duration=endpoint_case.duration-offset)
    restarts = []
    def create_restart(*args):
        def restart(at):
            restarts.append(at)
            return iter([])
        return restart
    monkeypatch.setattr(tr, "_loop_guard_restart", create_restart)
    (tr.resume_transcription if resume else tr.transcribe)(task)
    assert len(task.output_paths) == 3
    assert [s["text"] for s in endpoint_case.writes[-1]] == (["prior", "valid"] if resume else ["valid"])
    assert all("repeat" not in Path(p).read_text(encoding="utf-8") for p in task.output_paths)
    assert restarts == []
    records = [json.loads(p.read_text(encoding="utf-8")) for p in cp.partials_dir().glob("*.timing-recovery.json")]
    assert sorted(r["segments"][-1]["start"] for r in records) == pytest.approx([seg.start+offset for seg in raw])


def test_repeated_empty_capture_creates_only_mandatory_record(endpoint_case):
    task = output_task(endpoint_case)
    task._audio_end = 2.0
    task.paused = True
    raw = [{"start": 2.6, "end": 2.5, "text": "rejected"}]
    for attempt in range(3):
        with pytest.raises(tr._TimingBoundsError, match="paused; no additional text was recovered"):
            tr._enforce_decoded_audio_end(task, list(raw), recovery=lambda: raw,
                                         remaining=iter([]), convert=dict)
        assert len(list(cp.partials_dir().glob("*.timing-recovery.json"))) == attempt + 1


def test_conversion_failure_preserves_whole_last_text_then_stops(endpoint_case, monkeypatch):
    monkeypatch.setattr(tr, "_TIMING_TAIL_TEXT_CHARS", 1)
    task = output_task(endpoint_case)
    remaining = iter([SimpleNamespace(text="whole available text"), SimpleNamespace(text="unread")])
    def convert(value):
        raise ValueError("broken clocks")
    kept, stopped = tr._capture_timing_tail(task, [], remaining, convert, "bad timing")
    assert stopped == "conversion-error:ValueError"
    assert json.loads(Path(kept).read_text(encoding="utf-8"))["segments"] == [
        {"text": "whole available text", "timing_unavailable": True}]
    assert next(remaining).text == "unread"


@pytest.mark.skipif(sys.platform != "win32", reason="native Windows OSError contract")
@pytest.mark.parametrize("winerror", [5, 112])
def test_tail_storage_failure_preserves_windows_error_and_filenames(endpoint_case, monkeypatch, winerror):
    task = output_task(endpoint_case)
    task._audio_end = 2.0
    raw = [{"start": 2.6, "end": 2.5, "text": "rejected"}]
    error = OSError(0, "synthetic refusal", str(endpoint_case.audio), winerror,
                    str(endpoint_case.audio.with_suffix(".json")))
    identity = (type(error), error.errno, error.winerror, error.filename, error.filename2)
    keep = tr._keep_timing_recovery
    paths = []
    def save(source, segments, reason):
        if paths:
            raise error
        paths.append(keep(source, segments, reason))
        return paths[0]
    monkeypatch.setattr(tr, "_keep_timing_recovery", save)
    with pytest.raises(OSError) as caught:
        tr._enforce_decoded_audio_end(task, list(raw), recovery=lambda: raw,
                                     remaining=iter([{"text": "later"}]), convert=dict)
    assert caught.value is error
    assert identity == (type(error), error.errno, error.winerror, error.filename, error.filename2)
    assert paths[0] in str(error) and "synthetic refusal" in str(error)
