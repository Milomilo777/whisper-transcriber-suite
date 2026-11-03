"""CUDA retries preserve decoded text and stay downgraded for the session."""
from __future__ import annotations

from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from core import transcriber as tr
from core.task import TranscriptionTask


OOM = "CUDA failed with error out of memory"


def segment(start, end, text):
    return SimpleNamespace(start=start, end=end, text=text, words=[])


class Engine:
    def __init__(self, scripts, device="cuda", compute="float16"):
        self.scripts = list(scripts)
        self.calls = []
        self.model = SimpleNamespace(device=device, compute_type=compute)

    def transcribe(self, audio, **kwargs):
        self.calls.append((audio, dict(kwargs)))
        script = self.scripts.pop(0)
        if isinstance(script, BaseException):
            raise script

        def generate():
            for item in script:
                if isinstance(item, BaseException):
                    raise item
                yield item

        return generate(), SimpleNamespace(language="en", language_probability=0.9, duration=20)


@pytest.fixture
def decode(monkeypatch, tmp_path):
    from core import _checkpoint as cp

    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path)
    cfg = {**tr.config, "transcribe_backend": "faster_whisper", "model_path": "fake-model",
           "model_size": "small", "batch_size": 16, "word_timestamps": False,
           "demucs_enabled": False, "denoise_enabled": False, "loop_guard_repeats": 0}
    monkeypatch.setattr(tr, "config", cfg)
    monkeypatch.setattr(tr, "MODEL_READY", True)
    monkeypatch.setattr(tr, "MODEL_ERROR", None)
    for name, value in (("device", "cuda"), ("compute_type", "float16"),
                        ("_EFFECTIVE_DEVICE", "cuda"), ("_EFFECTIVE_COMPUTE_TYPE", "float16"),
                        ("_REQUESTED_DEVICE", "cuda"), ("_DEVICE_DOWNGRADED", False)):
        monkeypatch.setattr(tr, name, value)
    monkeypatch.setattr(tr, "_CUDA_BATCH_SIZE", 0, raising=False)
    monkeypatch.setattr(tr, "PIPELINE", None)
    monkeypatch.setattr(tr, "_runtime_overrides_scope", lambda task: nullcontext(cfg))
    monkeypatch.setattr(tr, "get_duration", lambda path: 20.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda path: None)
    monkeypatch.setattr(tr, "_apply_language_prior", lambda *a, **k: None)
    monkeypatch.setattr(tr, "_rescue_collapsed", lambda task, data, *a, **k: data)
    monkeypatch.setattr(tr, "_run_post_pipeline", lambda *a, **k: 0)
    written = []

    def write(base, data, *args, **kwargs):
        written.append([dict(s) for s in data])
        return []

    monkeypatch.setattr(tr, "_write_outputs", write)
    slices = []

    def slice_audio(src, start, directory, **kwargs):
        path = tmp_path / f"slice-{len(slices)}.wav"
        path.write_bytes(b"audio")
        slices.append((src, start, path))
        return str(path)

    monkeypatch.setattr(tr, "_slice_audio_from", slice_audio)
    audio = tmp_path / "input.wav"
    audio.write_bytes(b"audio")
    return str(audio), written, slices


def test_batched_oom_retries_only_tail_and_remembers_batch(decode, monkeypatch):
    audio, written, slices = decode
    engine = Engine([
        [segment(0, 5, "first"), RuntimeError(OOM)],
        [segment(0, 4, "tail")],
        [segment(0, 3, "next file")],
    ])
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "PIPELINE", engine)
    logs = []
    tr.transcribe(TranscriptionTask(audio), log_cb=logs.append)
    tr.transcribe(TranscriptionTask(audio), log_cb=logs.append)
    assert [c[1]["batch_size"] for c in engine.calls] == [16, 1, 1]
    assert [(s["start"], s["end"], s["text"]) for s in written[0]] == [
        (0, 5, "first"), (5, 9, "tail")]
    assert slices[0][:2] == (audio, 5)
    assert all(not path.exists() for _, _, path in slices)
    assert len([line for line in logs if "CUDA" in line]) == 1


def test_unbatched_oom_quantizes_then_uses_cpu_without_losing_text(decode, monkeypatch):
    audio, written, slices = decode
    gpu = Engine([[segment(0, 5, "first"), RuntimeError(OOM)]])
    quantized = Engine([[segment(0, 3, "second"), RuntimeError(OOM)]], compute="int8_float16")
    cpu = Engine([[segment(0, 2, "third")], [segment(0, 1, "next")]], "cpu", "int8")
    loads = []

    def load(path, *, device, compute_type):
        loads.append((device, compute_type))
        return quantized if device == "cuda" else cpu

    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "WhisperModel", load)
    monkeypatch.setattr(tr, "_wrap_for_batched", lambda model: None)
    tr.transcribe(TranscriptionTask(audio))
    tr.transcribe(TranscriptionTask(audio))
    assert loads == [("cuda", "int8_float16"), ("cpu", "int8")]
    assert [(s["start"], s["end"], s["text"]) for s in written[0]] == [
        (0, 5, "first"), (5, 8, "second"), (8, 10, "third")]
    assert [start for _, start, _ in slices] == [5, 8]
    assert tr.get_effective_device().device == "cpu"
    assert tr.get_effective_device().downgraded


def test_resumed_tail_recovers_without_repeating_checkpoint(decode, monkeypatch):
    from core import _checkpoint as cp

    audio, written, slices = decode
    task = TranscriptionTask(audio)
    tr._note_run_identity(task)
    tr._write_periodic_checkpoint(task, [{"start": 0, "end": 7, "text": "saved"}], 7, "en", 0.9, None)
    engine = Engine([[segment(0, 3, "new"), RuntimeError(OOM)], [segment(0, 2, "tail")]])
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "PIPELINE", engine)
    assert tr.resume_transcription(task)
    assert [c[1]["batch_size"] for c in engine.calls] == [16, 1]
    assert [(s["start"], s["end"], s["text"]) for s in written[0]] == [
        (0, 7, "saved"), (7, 10, "new"), (10, 12, "tail")]
    assert [start for _, start, _ in slices] == [7, 3]
    assert cp.load_checkpoint(audio) is None


def test_cpu_error_is_not_retried_and_partial_is_saved(decode, monkeypatch):
    from core import _checkpoint as cp

    audio, _, _ = decode
    engine = Engine([[segment(0, 5, "saved"), RuntimeError(OOM)]], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "_EFFECTIVE_DEVICE", "cpu")
    with pytest.raises(RuntimeError, match=OOM):
        tr.transcribe(TranscriptionTask(audio))
    assert len(engine.calls) == 1
    assert cp.load_checkpoint(audio)["segments"][0]["text"] == "saved"


def test_live_chunk_recovers_lazy_decode(decode, monkeypatch):
    audio, _, slices = decode
    gpu = Engine([[segment(0, 2, "first"), RuntimeError(OOM)]], compute="int8_float16")
    cpu = Engine([[segment(0, 1, "tail")]], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "compute_type", "int8_float16")
    monkeypatch.setattr(tr, "WhisperModel", lambda *a, **k: cpu)
    result = tr.transcribe_chunk_to_text(audio)
    assert result["text"] == "first tail"
    assert result["segments"][-1]["end"] == 3
    assert slices[0][1] == 2


def test_faster_whisper_backend_recovers_segment_iteration(decode, monkeypatch):
    from core.backends.faster_whisper_be import FasterWhisperBackend

    audio, _, _ = decode
    engine = Engine([[segment(0, 2, "first"), RuntimeError(OOM)], [segment(0, 1, "tail")]])
    backend = FasterWhisperBackend()
    backend._model = backend._pipeline = engine
    backend._ready = True
    backend._device = "cuda"
    segments, _ = backend.transcribe_to_segments(audio)
    assert [s["text"] for s in segments] == ["first", "tail"]
    assert segments[-1]["start"] == 2
    assert [c[1]["batch_size"] for c in engine.calls] == [16, 1]


def test_checkpoint_is_saved_before_reloading_weights(decode, monkeypatch):
    from core import _checkpoint as cp

    audio, _, _ = decode
    gpu = Engine([[segment(0, 5, "durable"), RuntimeError(OOM)]], compute="int8_float16")
    cpu = Engine([[segment(0, 1, "tail")]], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "compute_type", "int8_float16")

    def load(*args, **kwargs):
        assert cp.load_checkpoint(audio)["segments"][0]["text"] == "durable"
        return cpu

    monkeypatch.setattr(tr, "WhisperModel", load)
    tr.transcribe(TranscriptionTask(audio))


@pytest.mark.parametrize("rnnt", [False, True])
def test_transformers_retries_same_piece_and_keeps_previous_windows(monkeypatch, rnnt):
    import numpy as np
    from core.backends import nvidia_asr as na

    backend = na.NvidiaAsrBackend()
    backend._ready = True
    backend._device = "cuda:0"
    backend._supports_word_ts = False
    calls = []

    def infer(audio, **kwargs):
        raw = audio["raw"] if isinstance(audio, dict) else audio
        calls.append((backend._device, len(raw)))
        if len(calls) in (2, 3):
            raise RuntimeError("CUDA out of memory.")
        return "piece" if rnnt else {"text": "piece"}

    if rnnt:
        backend._runner = infer
    else:
        backend._pipe = infer
    monkeypatch.setattr(na, "_decode_window", lambda *a: np.ones(4 * na.TARGET_SR))
    monkeypatch.setattr(na, "plan_chunks", lambda *a: [(0, 4), (4, 8), (8, 12)])
    monkeypatch.setattr(na, "speech_pieces", lambda audio: [(0, len(audio))])
    cpu_loads = []
    monkeypatch.setattr(na, "_import_torch_and_transformers", lambda: (SimpleNamespace(float32="f32"), None))

    def cpu_pipe(*a, **k):
        cpu_loads.append(True)
        return infer

    monkeypatch.setattr(na, "_build_pipeline", cpu_pipe)
    monkeypatch.setattr(na, "_build_rnnt", cpu_pipe)
    logs = []
    segments, _ = backend.transcribe_to_segments("fake.wav", duration=12, log_cb=logs.append)
    assert segments[0]["start"] == 0 and segments[-1]["end"] == 12
    assert len([s for s in segments if s["start"] == 0]) == 1
    assert backend.device == "cpu"
    assert len(cpu_loads) == 1
    assert calls[:3] == [("cuda:0", 4 * na.TARGET_SR), ("cuda:0", 4 * na.TARGET_SR),
                         ("cuda:0", 2 * na.TARGET_SR)]
    assert len([s for s in logs if "CUDA" in s]) == 2


def test_clipped_decode_recovers_on_source_timeline(decode, monkeypatch):
    audio, written, slices = decode
    monkeypatch.setattr(tr, "get_duration", lambda path: 200.0)
    monkeypatch.setattr(tr, "compute_type", "int8_float16")
    gpu = Engine([[segment(0, 5, "clip start"), RuntimeError(OOM)]])
    cpu = Engine([[segment(0, 2, "clip tail")]], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "WhisperModel", lambda *a, **k: cpu)
    task = TranscriptionTask(audio)
    task.clip_start, task.clip_end = 100, 120
    tr.transcribe(task)
    assert [(s["start"], s["end"]) for s in written[0]] == [(100, 105), (105, 107)]
    assert [start for _, start, _ in slices] == [100, 5]
    assert all(not path.exists() for _, _, path in slices)


def test_gpu_model_is_released_before_cpu_model_is_allocated(decode, monkeypatch):
    import weakref

    audio, _, _ = decode
    monkeypatch.setattr(tr, "compute_type", "int8_float16")
    monkeypatch.setattr(tr, "MODEL", Engine([[segment(0, 1, "kept"), RuntimeError(OOM)]]))
    previous = weakref.ref(tr.MODEL)
    cpu = Engine([[segment(0, 1, "tail")]], "cpu", "int8")

    def load(*a, **k):
        assert previous() is None
        return cpu

    monkeypatch.setattr(tr, "WhisperModel", load)
    tr.transcribe(TranscriptionTask(audio))


def test_collapsed_window_retry_keeps_completed_checkpoint(decode, monkeypatch):
    import numpy as np
    from core import _checkpoint as cp, collapse_rescue as cr
    from core.backends import nvidia_asr as na

    # Exercise the real rescue wiring, which normally receives arrays rather
    # than source paths and must preserve the original completed transcript.
    audio, _, _ = decode
    monkeypatch.setattr(tr, "_rescue_collapsed", RESCUE_COLLAPSED)
    monkeypatch.setattr(tr, "compute_type", "int8_float16")
    monkeypatch.setattr(tr, "MODEL", Engine([[segment(0, 1, "rescued first"), RuntimeError(OOM)]]))
    cpu = Engine([[segment(0, 1, "rescued tail")]], "cpu", "int8")
    task = TranscriptionTask(audio)
    tr._note_run_identity(task)
    data = [{"start": 0, "end": 3, "text": "original"}]

    def load(*a, **k):
        saved = cp.load_checkpoint(audio)
        assert saved["transcription_completed"] and saved["segments"] == data
        return cpu

    monkeypatch.setattr(tr, "WhisperModel", load)
    monkeypatch.setattr(na, "_decode_window", lambda *a: np.ones(5 * 16000))
    monkeypatch.setattr(cr, "find_suspect_spans", lambda *a: [(5, 10)])

    def rescue(data, duration, speech, transcribe, **kwargs):
        return data + transcribe(5, 10), SimpleNamespace(lines=lambda: [], rescued=[], kept=[])

    monkeypatch.setattr(cr, "rescue", rescue)
    result = tr._rescue_collapsed(task, data, audio, {}, False, "en", 20, None)
    assert [s["text"] for s in result] == ["original", "rescued first", "rescued tail"]
    assert result[-1]["start"] == 6
    assert len(cpu.calls[0][0]) == 4 * 16000


RESCUE_COLLAPSED = tr._rescue_collapsed


def test_backend_reload_keeps_session_cpu_fallback(monkeypatch, tmp_path):
    from core import hardware
    from core.backends import faster_whisper_be as fw

    backend = fw.FasterWhisperBackend()
    backend._device, backend._compute_type = "cpu", "int8"
    backend._requested_device, backend._downgraded = "cuda", True
    monkeypatch.setattr(fw, "load_config", lambda **k: {"model_path": str(tmp_path)})
    monkeypatch.setattr(fw, "_detect_device", lambda cfg: ("cuda", "float16"))
    monkeypatch.setattr(hardware, "prepare_cuda_runtime", lambda: None)
    monkeypatch.setattr(hardware, "warm_up_cuda_model", lambda model: None)
    calls = []

    def load(path, *, device, compute_type):
        calls.append((device, compute_type))
        return Engine([], device, compute_type)

    monkeypatch.setattr(fw, "WhisperModel", load)
    backend.unload()
    assert backend.load_existing()
    assert calls == [("cpu", "int8")]
    assert backend.requested_device == "cuda" and backend.downgraded


@pytest.mark.parametrize("exc", [SystemExit(1), KeyboardInterrupt()])
def test_decoder_baseexception_keeps_latest_checkpoint(decode, monkeypatch, exc):
    from core import _checkpoint as cp

    audio, _, _ = decode
    monkeypatch.setattr(tr, "MODEL", Engine([[segment(0, 2, "latest text"), exc]]))
    with pytest.raises(type(exc)):
        tr.transcribe(TranscriptionTask(audio))
    assert cp.load_checkpoint(audio)["segments"][0]["text"] == "latest text"
