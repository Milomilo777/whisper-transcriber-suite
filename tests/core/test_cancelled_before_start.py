"""A task cancelled before it starts does none of the expensive set-up work.

The worker applies a cancel that overtook the dispatch (or a lost parent)
before ``transcribe()`` runs. Until the first segment arrives nothing looked at
the flag, so a dead task still waited for the model, ran vocal separation,
ffprobe, the denoise pass and the ffmpeg slice first.
"""
from __future__ import annotations

import pytest

from core import transcriber as t
from core.task import TranscriptionTask


def _forbid(monkeypatch, *names: str) -> None:
    def boom(*a, **k):
        raise AssertionError("set-up work ran for a task that was already cancelled")

    for name in names:
        monkeypatch.setattr(t, name, boom)


def _cancelled_task() -> TranscriptionTask:
    task = TranscriptionTask("never-read.wav")
    task.cancelled = True
    return task


def test_transcribe_returns_at_once_for_a_cancelled_task(monkeypatch):
    _forbid(monkeypatch, "_runtime_overrides_scope", "get_duration", "_ensure_default_backend_loaded")
    logs: list[str] = []
    assert t.transcribe(_cancelled_task(), log_cb=logs.append) is None
    assert any("cancelled" in m.lower() for m in logs)


def test_resume_returns_handled_for_a_cancelled_task(monkeypatch):
    _forbid(monkeypatch, "_runtime_overrides_scope", "_slice_audio_from", "_ensure_default_backend_loaded")
    monkeypatch.setattr(t._checkpoint, "load_checkpoint", lambda *_a, **_k: pytest.fail("checkpoint read"))
    logs: list[str] = []
    # True = handled: the worker must not fall back to a fresh transcribe().
    assert t.resume_transcription(_cancelled_task(), log_cb=logs.append) is True
    assert any("cancelled" in m.lower() for m in logs)


def test_an_uncancelled_task_still_gets_the_set_up(monkeypatch):
    # Control: the guard must not skip a live task.
    entered: list[bool] = []

    class _Scope:
        def __enter__(self):
            entered.append(True)
            raise RuntimeError("stop here")

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(t, "_runtime_overrides_scope", lambda task: _Scope())
    with pytest.raises(RuntimeError, match="stop here"):
        t.transcribe(TranscriptionTask("x.wav"))
    assert entered == [True]
