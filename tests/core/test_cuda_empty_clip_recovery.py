"""Whole-file clip requests keep their unprocessed tail after lazy CUDA errors."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from core import transcriber as tr
from core.task import TranscriptionTask
from tests.core.test_cuda_decode_recovery import Engine, OOM, decode, segment


class ClosingIterator:
    def __init__(self, iterator):
        self.iterator = iterator
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        return next(self.iterator)

    def close(self):
        self.closed = True
        self.iterator.close()


class TrackingEngine(Engine):
    def __init__(self, scripts, compute="float16"):
        super().__init__(scripts, compute=compute)
        self.iterators = []

    def transcribe(self, audio, **kwargs):
        iterator, info = super().transcribe(audio, **kwargs)
        captured = ClosingIterator(iterator)
        self.iterators.append(captured)
        return captured, info


@pytest.fixture(params=[False, True], ids=["global", "language-slot"])
def lazy_decode(decode, monkeypatch, request):
    audio, _, slices = decode
    model = TrackingEngine([[segment(0, 5, "prefix"), RuntimeError(OOM)]])
    replacement = TrackingEngine([[segment(0, 3, "tail")]], compute="int8_float16")
    pipeline = Engine([RuntimeError("This VAD-off request must use sequential CUDA")])
    inactive_model, inactive_pipeline = Engine([]), Engine([])
    local = threading.local()
    folder = "language-slot-model" if request.param else "fake-model"
    if request.param:
        local.slot = SimpleNamespace(model=model, pipeline=pipeline, folder=folder)
    monkeypatch.setattr(tr, "_LM_RUNNER", local)
    monkeypatch.setattr(tr, "MODEL", inactive_model if request.param else model)
    monkeypatch.setattr(tr, "PIPELINE", inactive_pipeline if request.param else pipeline)
    monkeypatch.setattr(tr, "_vad_window_seconds", lambda: 0)
    monkeypatch.setattr(tr, "mixed_language_pair", lambda task: None)
    loads = []

    def reload(path, *, device, compute_type):
        loads.append((path, device, compute_type))
        return replacement

    monkeypatch.setattr(tr, "WhisperModel", reload)
    monkeypatch.setattr(tr, "_wrap_for_batched", lambda engine: None)
    return SimpleNamespace(
        audio=audio, slices=slices, model=model, replacement=replacement,
        pipeline=pipeline, inactive_model=inactive_model,
        inactive_pipeline=inactive_pipeline, loads=loads, folder=folder,
        local=local,
    )


@pytest.mark.parametrize("kind,clips", [
    ("omitted", None), ("none", None), ("empty-list", []),
    ("empty-string", ""), ("flat-list", [0.0, 20.0]),
    ("comma-string", "0,20"),
], ids=lambda value: value if isinstance(value, str) and value else None)
def test_lazy_cuda_recovery_keeps_whole_file_or_requested_clip_tail(lazy_decode, kind, clips):
    state = lazy_decode
    options = {"language": "en", "vad_filter": False, "batch_size": 4}
    if kind != "omitted":
        options["clip_timestamps"] = clips
    explicit = kind in {"flat-list", "comma-string"}
    task = TranscriptionTask(state.audio)
    task.language = "en"
    runner = tr._whisper_runner(task, batched=not explicit)
    iterator, _ = runner.transcribe(state.audio, **options)
    rows = list(iterator)

    assert [(row.start, row.end, row.text) for row in rows] == [
        (0, 5, "prefix"), (5, 8, "tail"),
    ]
    assert state.loads == [(state.folder, "cuda", "int8_float16")]
    assert task._telemetry_recovery == "retried_ok"
    assert tr.device == "cuda"
    assert not state.pipeline.calls
    assert not state.inactive_model.calls and not state.inactive_pipeline.calls
    for engine in (state.model, state.replacement):
        assert len(engine.calls) == 1
        assert engine.calls[0][1]["vad_filter"] is False
        assert "batch_size" not in engine.calls[0][1]
        assert engine.iterators and all(item.closed for item in engine.iterators)
    if explicit:
        assert state.model.calls[0][1]["clip_timestamps"] == clips
        assert state.replacement.calls[0][1]["clip_timestamps"] == [0.0, 15.0]
    else:
        assert "clip_timestamps" not in state.model.calls[0][1]
        assert "clip_timestamps" not in state.replacement.calls[0][1]
    assert [start for _, start, _ in state.slices] == [5]
    assert state.replacement.calls[0][0] == str(state.slices[0][2])
    assert all(not path.exists() for _, _, path in state.slices)
    installed = state.local.slot.model if hasattr(state.local, "slot") else tr.MODEL
    assert installed is state.replacement


@pytest.mark.parametrize("clips,error", [(False, TypeError), (0, TypeError), (" ", ValueError)])
def test_empty_clip_repair_does_not_accept_other_malformed_clips(lazy_decode, clips, error):
    state = lazy_decode
    task = TranscriptionTask(state.audio)
    task.language = "en"
    iterator, _ = tr._whisper_runner(task).transcribe(
        state.audio, language="en", vad_filter=False, clip_timestamps=clips,
    )
    with pytest.raises(error):
        list(iterator)
    assert not state.replacement.calls
    assert all(item.closed for item in state.model.iterators)
    assert all(not path.exists() for _, _, path in state.slices)
