"""CUDA decode routing honors VAD and the engine's distinct clip contracts."""
from __future__ import annotations

import threading
from types import SimpleNamespace

import pytest

from core import transcriber as tr
from core.task import TranscriptionTask


OOM = "CUDA failed with error out of memory"


class Sequential:
    def __init__(self, text, compute="float16"):
        self.text = text
        self.calls = []
        self.failures = []
        self.failures_raised = 0
        self.model = SimpleNamespace(device="cuda", compute_type=compute)

    def transcribe(self, audio, **options):
        self.calls.append((audio, dict(options)))
        if "batch_size" in options:
            raise TypeError("Sequential transcription has no batch_size argument")
        clips = options.get("clip_timestamps", "0")
        if not isinstance(clips, str) and not all(isinstance(t, (int, float)) for t in clips):
            raise TypeError("Sequential clips must be a string or flat numeric list")
        if self.failures:
            self.failures_raised += 1
            raise self.failures.pop(0)
        return _result(self.text)


class Batched:
    def __init__(self, text):
        self.text = text
        self.calls = []
        self.failures = []
        self.failures_raised = 0

    def transcribe(self, audio, **options):
        self.calls.append((audio, dict(options)))
        # Adapted from faster-whisper (https://github.com/SYSTRAN/faster-whisper/blob/v1.2.1/faster_whisper/transcribe.py) — model its long-audio batched clip contract without inference.
        clips = options.get("clip_timestamps")
        if clips:
            if not isinstance(clips, list) or not all(
                isinstance(clip, dict)
                and set(clip) == {"start", "end"}
                and all(isinstance(value, (int, float)) for value in clip.values())
                for clip in clips
            ):
                raise TypeError("Batched clips require second-based start/end dictionaries")
        elif not options.get("vad_filter", True):
            # The fixture represents 600 seconds, beyond the short-audio
            # exception in the installed API (duration < chunk_length).
            raise RuntimeError(
                "No clip timestamps found. Set 'vad_filter' to True "
                "or provide 'clip_timestamps'."
            )
        if self.failures:
            self.failures_raised += 1
            raise self.failures.pop(0)
        return _result(self.text)


def _result(text):
    segment = SimpleNamespace(start=0.0, end=1.0, text=text, words=[])
    info = SimpleNamespace(language="en", language_probability=1.0, duration=600.0)
    return iter([segment]), info


@pytest.fixture(params=[False, True], ids=["global", "language-slot"])
def routing(request, monkeypatch):
    global_model, global_pipeline = Sequential("global text"), Batched("global text")
    slot_model, slot_pipeline = Sequential("slot text"), Batched("slot text")
    monkeypatch.setattr(tr, "MODEL", global_model)
    monkeypatch.setattr(tr, "PIPELINE", global_pipeline)
    for name, value in (("device", "cuda"), ("compute_type", "float16"),
                        ("_EFFECTIVE_DEVICE", "cuda"), ("_EFFECTIVE_COMPUTE_TYPE", "float16"),
                        ("_REQUESTED_DEVICE", "cuda"), ("_DEVICE_DOWNGRADED", False),
                        ("_CUDA_BATCH_SIZE", 0)):
        monkeypatch.setattr(tr, name, value)
    monkeypatch.setattr(tr, "config", {**tr.config, "model_path": "global-model"})
    local = threading.local()
    if request.param:
        local.slot = SimpleNamespace(model=slot_model, pipeline=slot_pipeline, folder="slot-model")
    monkeypatch.setattr(tr, "_LM_RUNNER", local)
    monkeypatch.setattr(tr, "_vad_window_seconds", lambda: None)

    def unexpected_reload(*args, **kwargs):
        raise AssertionError("A valid decode route must not reload or force CPU")

    monkeypatch.setattr(tr, "WhisperModel", unexpected_reload)
    return SimpleNamespace(
        model=slot_model if request.param else global_model,
        pipeline=slot_pipeline if request.param else global_pipeline,
        other_model=global_model if request.param else slot_model,
        other_pipeline=global_pipeline if request.param else slot_pipeline,
        expected_text="slot text" if request.param else "global text",
        expected_folder="slot-model" if request.param else "global-model",
    )


def _decode(routing, *, batched=True, **options):
    task = TranscriptionTask("speech.wav")
    decoded, _ = tr._whisper_runner(task, batched=batched).transcribe(
        "speech.wav", language="en", **options,
    )
    assert [segment.text for segment in decoded] == [routing.expected_text]
    assert tr.device == "cuda"
    assert not routing.other_model.calls
    assert not routing.other_pipeline.calls
    return task


@pytest.mark.parametrize("clip_options", [{}, {"clip_timestamps": None}, {"clip_timestamps": []}], ids=["omitted-clips", "none-clips", "empty-clips"])
def test_cuda_transcription_without_vad_has_a_valid_decode_route(routing, clip_options):
    _decode(routing, vad_filter=False, batch_size=4, **clip_options)
    # The contract is successful GPU decoding, not one particular fix strategy.
    calls = routing.model.calls + routing.pipeline.calls
    assert calls and all(options.get("vad_filter") is False for _, options in calls)
    assert _whole_file_request_preserved(routing.model.calls, routing.pipeline.calls)


@pytest.mark.parametrize("vad_options", [{}, {"vad_filter": True}], ids=["default-vad", "enabled-vad"])
def test_vad_enabled_keeps_supported_cuda_batching(routing, vad_options):
    _decode(routing, batch_size=4, **vad_options)
    assert not routing.model.calls
    assert routing.pipeline.calls[0][1]["batch_size"] == 4


@pytest.mark.parametrize("clips", [[{"start": 0.0, "end": 1.0}], [{"start": 0.0, "end": 0.5}, {"start": 1.0, "end": 1.5}]], ids=["one-window", "two-windows"])
def test_explicit_batched_clip_dictionaries_have_a_valid_gpu_route(routing, clips):
    _decode(routing, vad_filter=False, clip_timestamps=clips, batch_size=4)
    expected = [(float(c["start"]), float(c["end"])) for c in clips]
    calls = routing.model.calls + routing.pipeline.calls
    assert calls
    for _, options in calls:
        assert options.get("vad_filter") is False
        assert _clip_intervals(options.get("clip_timestamps")) == expected


def _clip_intervals(clips):
    if isinstance(clips, list) and clips and isinstance(clips[0], dict):
        return [(float(c["start"]), float(c["end"])) for c in clips]
    stamps = [float(t) for t in clips.split(",")] if isinstance(clips, str) else list(clips or [])
    if not stamps:
        stamps = [0.0]
    if len(stamps) % 2:
        stamps.append(600.0)
    return list(zip(stamps[::2], stamps[1::2]))


def _complete_coverage(intervals, *, max_width=None):
    cursor = 0.0
    for start, end in intervals:
        if abs(start - cursor) > 1e-9 or not 0 <= start < end <= 600.0:
            return False
        if max_width is not None and end - start > max_width + 1e-9:
            return False
        cursor = end
    return abs(cursor - 600.0) <= 1e-9


def _whole_file_request_preserved(sequential_calls, batched_calls):
    return all(_complete_coverage(_clip_intervals(options.get("clip_timestamps"))) for _, options in sequential_calls) and all(_complete_coverage(_clip_intervals(options.get("clip_timestamps")), max_width=30.0) for _, options in batched_calls)


@pytest.mark.parametrize("sequential,clips,expected", [
    (False, [{"start": 0.0, "end": 600.0}], False),
    (False, [{"start": 0.0, "end": 30.0}], False),
    (False, [{"start": float(start), "end": float(start + 30)} for start in range(0, 600, 30)], True),
    (True, "0", True),
], ids=["reject-oversized-batch-clip", "reject-first-window-only", "complete-bounded-batch-windows", "sequential-whole-file"])
def test_implicit_long_file_coverage_guard_rejects_truncating_workarounds(sequential, clips, expected):
    call = [("speech.wav", {"clip_timestamps": clips})]
    assert _whole_file_request_preserved(call if sequential else [], [] if sequential else call) is expected


@pytest.mark.parametrize("clips", ["0,1", [0.0, 1.0]], ids=["comma-string", "flat-list"])
def test_sequential_clips_drop_the_incompatible_batch_size(routing, clips):
    _decode(routing, batched=False, vad_filter=False, clip_timestamps=clips, batch_size=4)
    assert routing.model.calls[0][1]["clip_timestamps"] == clips
    assert "batch_size" not in routing.model.calls[0][1]
    assert not routing.pipeline.calls


@pytest.mark.parametrize("vad_filter", [False, True], ids=["vad-off", "vad-on"])
def test_supported_routing_retains_cuda_oom_recovery(routing, vad_filter, monkeypatch):
    # Either valid routing strategy must recover from its actual selected
    # engine's first OOM. Do not require batch reduction or quantization here.
    routing.model.failures.append(RuntimeError(OOM))
    routing.pipeline.failures.append(RuntimeError(OOM))
    loads = []
    replacements = []

    def reload(path, *, device, compute_type):
        loads.append((path, device, compute_type))
        assert path == routing.expected_folder
        assert device == "cuda"
        model = Sequential(routing.expected_text, compute=compute_type)
        replacements.append(model)
        return model

    monkeypatch.setattr(tr, "WhisperModel", reload)
    monkeypatch.setattr(tr, "_wrap_for_batched", lambda model: None)
    task = _decode(routing, vad_filter=vad_filter, batch_size=4)
    assert routing.model.failures_raised + routing.pipeline.failures_raised == 1
    assert task._telemetry_recovery in {"cuda_batch_reduced", "retried_ok"}
    assert all(options.get("vad_filter") is vad_filter for _, options in routing.model.calls + routing.pipeline.calls)
    for replacement in replacements:
        assert replacement.calls and all("batch_size" not in options for _, options in replacement.calls)
        assert all(options.get("vad_filter") is vad_filter for _, options in replacement.calls)
    if not vad_filter:
        assert _whole_file_request_preserved(routing.model.calls + [call for model in replacements for call in model.calls], routing.pipeline.calls)


def test_cuda_without_batched_pipeline_keeps_whole_file_and_vad_choice(routing):
    # Versions without BatchedInferencePipeline still support sequential CUDA.
    from core import transcriber as transcriber

    if getattr(transcriber._LM_RUNNER, "slot", None) is not None:
        transcriber._LM_RUNNER.slot.pipeline = None
    else:
        transcriber.PIPELINE = None
    _decode(routing, vad_filter=False, batch_size=4)
    assert routing.model.calls
    assert not routing.pipeline.calls
    assert all(options.get("vad_filter") is False for _, options in routing.model.calls)
    assert all("batch_size" not in options for _, options in routing.model.calls)
    assert _whole_file_request_preserved(routing.model.calls, [])


@pytest.mark.parametrize("clips", [False, 0], ids=["false", "zero"])
@pytest.mark.parametrize("batched", [False, True], ids=["sequential", "batched"])
def test_malformed_clip_values_are_not_normalized_to_whole_audio(routing, clips, batched):
    task = TranscriptionTask("voice.wav")
    with pytest.raises((TypeError, RuntimeError)):
        tr._whisper_runner(task, batched=batched).transcribe(
            "voice.wav", vad_filter=False, clip_timestamps=clips,
        )
