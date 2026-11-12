"""Sequential CUDA routing preserves loop recovery and persisted speech."""
from __future__ import annotations

import pytest

from core import _checkpoint as cp
from core import transcriber as tr
from core.task import TranscriptionTask
from tests.core.test_cuda_decode_recovery import Engine, decode, segment


@pytest.mark.parametrize("pipeline_present", [True, False], ids=["available-cuda-pipeline", "sequential-control"])
@pytest.mark.parametrize("resume", [False, True], ids=["normal-task", "resume-task"])
def test_vad_off_sequential_route_restarts_loop_without_losing_tail(
    decode, monkeypatch, pipeline_present, resume
):
    audio, written, slices = decode
    monkeypatch.setattr(tr, "_vad_parameters", lambda: None)
    monkeypatch.setattr(tr, "_vad_window_seconds", lambda: 0)
    monkeypatch.setitem(tr.config, "loop_guard_repeats", 3)
    model = Engine([
        [segment(i, i + 1, "loop phrase") for i in range(10)],
        [segment(0, 4, "recovered useful tail")],
    ])
    pipeline = Engine([RuntimeError("The disabled-VAD route must select the model")])
    monkeypatch.setattr(tr, "MODEL", model)
    monkeypatch.setattr(tr, "PIPELINE", pipeline if pipeline_present else None)
    task = TranscriptionTask(audio)
    prior = []
    if resume:
        prior = [{"start": 0, "end": 7, "text": "durable saved prefix"}]
        tr._note_run_identity(task)
        tr._write_periodic_checkpoint(task, prior, 7, "en", 0.9, None)
        assert tr.resume_transcription(task)
    else:
        tr.transcribe(task)
    origin = 7 if resume else 0
    expected = [(row["start"], row["end"], row["text"]) for row in prior] + [
        (origin, origin + 1, "loop phrase"),
        (origin + 1, origin + 5, "recovered useful tail"),
    ]
    assert [(row["start"], row["end"], row["text"]) for row in written[-1]] == expected
    assert len(model.calls) == 2
    assert model.calls[1][1]["condition_on_previous_text"] is False
    assert all(call[1]["vad_filter"] is False for call in model.calls)
    assert all("batch_size" not in call[1] for call in model.calls)
    assert not pipeline.calls
    assert [start for _, start, _ in slices] == ([7, 1] if resume else [1])
    assert all(not path.exists() for _, _, path in slices)
    assert cp.load_checkpoint(audio) is None
