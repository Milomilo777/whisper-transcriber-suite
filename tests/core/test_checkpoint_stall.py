"""A persistently failing checkpoint target must not stall transcription.

Covers the bounded retry window in ``core._checkpoint.write_checkpoint``, the
scratch-file cleanup for every exception type, and the consecutive-failure
skip in ``core.transcriber._write_periodic_checkpoint``.
"""
from __future__ import annotations

import time

import pytest

from core import _checkpoint as cp
from core import transcriber as t
from core.task import TranscriptionTask


def _write(source: str, segments: list) -> None:
    cp.write_checkpoint(
        source, backend="faster_whisper", model_name="m", language="en",
        language_probability=0.9, cfg_fingerprint="x", last_end_time=1.0,
        segments=segments, checkpoint_time=time.time(),
    )


@pytest.fixture
def source(monkeypatch, tmp_path):
    monkeypatch.setattr(cp, "partials_dir", lambda: tmp_path)
    p = tmp_path / "audio.wav"
    p.write_bytes(b"x")
    return str(p)


def test_a_permanently_locked_target_stalls_one_write_for_about_a_second(
    monkeypatch, source, tmp_path,
):
    def always_denied(src, dst):
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(cp.os, "replace", always_denied)
    started = time.monotonic()
    with pytest.raises(PermissionError):
        _write(source, [])
    elapsed = time.monotonic() - started
    # Measured against the real default window (not patched): it must keep
    # retrying (the race fix) yet stay far below the old 5 s stall.
    assert elapsed >= cp._REPLACE_RETRY_SECONDS * 0.9
    assert elapsed < 2.5
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_non_oserror_failure_leaves_no_tmp_file(source, tmp_path):
    # An object json cannot serialise raises TypeError mid-write.
    with pytest.raises(TypeError):
        _write(source, [{"text": object()}])
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_successful_write_leaves_no_tmp_file(source, tmp_path):
    _write(source, [{"start": 0.0, "end": 1.0, "text": "a"}])
    assert list(tmp_path.glob("*.tmp")) == []
    assert cp.load_checkpoint(source) is not None


def _failing_writer(monkeypatch, calls: list):
    def fail(*a, **k):
        calls.append(1)
        raise PermissionError(13, "Access is denied")

    monkeypatch.setattr(t._checkpoint, "write_checkpoint", fail)


def _periodic(task, logs, periodic=True):
    t._write_periodic_checkpoint(
        task, [{"start": 0.0, "end": 1.0, "text": "a"}], 1.0, "en", 0.9,
        logs.append, periodic=periodic,
    )


def test_periodic_writes_stop_after_consecutive_failures(monkeypatch):
    calls: list = []
    _failing_writer(monkeypatch, calls)
    task = TranscriptionTask("audio.wav")
    logs: list[str] = []
    limit = t._CHECKPOINT_MAX_CONSECUTIVE_FAILURES

    for _ in range(limit + 5):
        _periodic(task, logs)

    assert len(calls) == limit
    disabled = [m for m in logs if "disabled for this run" in m]
    assert len(disabled) == 1


def test_cancel_and_final_writes_still_try_after_the_skip(monkeypatch):
    calls: list = []
    _failing_writer(monkeypatch, calls)
    task = TranscriptionTask("audio.wav")
    logs: list[str] = []
    for _ in range(t._CHECKPOINT_MAX_CONSECUTIVE_FAILURES):
        _periodic(task, logs)
    before = len(calls)

    _periodic(task, logs, periodic=False)  # the cancel / final-flush path

    assert len(calls) == before + 1


def test_a_success_resets_the_failure_count(monkeypatch):
    task = TranscriptionTask("audio.wav")
    task.checkpoint_failures = t._CHECKPOINT_MAX_CONSECUTIVE_FAILURES - 1
    monkeypatch.setattr(t._checkpoint, "write_checkpoint", lambda *a, **k: None)
    _periodic(task, [])
    assert task.checkpoint_failures == 0
