"""Recovery must preserve the successful calls made before CUDA retries existed."""
from __future__ import annotations

import gc
import weakref
from copy import deepcopy
from contextlib import nullcontext
from types import SimpleNamespace

import numpy as np
import pytest

from core import transcriber as tr, vad_window
from core.backends.faster_whisper_be import WhisperDecode
from core.task import TranscriptionTask
from tests.core.test_cuda_decode_recovery import Engine, OOM, decode, segment


@pytest.mark.parametrize("slot_active", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_live_chunk_matches_e27f18de_global_model_call(decode, monkeypatch, slot_active, mixed):
    audio, _, _ = decode
    engine = Engine([[segment(0, 1, "baseline")], [segment(0, 1, "baseline")]], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "device", "cpu")
    other = Engine([[segment(0, 1, "wrong slot")]], "cpu", "int8")
    monkeypatch.setattr(tr._LM_RUNNER, "slot", SimpleNamespace(model=other, pipeline=None)
                        if slot_active else None, raising=False)
    if mixed:
        monkeypatch.setattr(tr, "mixed_language_pair", lambda task: ("en", "fr"))
    wrapped = []
    monkeypatch.setattr(tr, "_two_language_runner", lambda model, pair: wrapped.append((model, pair)) or model)
    windows = []
    monkeypatch.setattr(vad_window, "windowed_vad", lambda seconds: windows.append(seconds) or nullcontext())
    task = TranscriptionTask(audio)
    task.language = "en"
    kwargs = tr._build_transcribe_kwargs(task)
    kwargs.pop("batch_size", None)
    kwargs["word_timestamps"] = False
    # e27f18de called MODEL directly, even with an LM slot or two languages.
    baseline, _ = engine.transcribe(audio, **kwargs)
    assert [s.text for s in baseline] == ["baseline"]
    expected = engine.calls.pop()
    result = tr.transcribe_chunk_to_text(audio, language="en")
    assert result["text"] == "baseline"
    assert engine.calls == [expected]
    assert other.calls == [] and wrapped == [] and windows == []


@pytest.mark.parametrize("slot_active", [False, True])
@pytest.mark.parametrize("mixed", [False, True])
def test_rescue_matches_e27f18de_selected_model_call(decode, monkeypatch, slot_active, mixed):
    from core import collapse_rescue as cr
    from core.backends import nvidia_asr as na
    from tests.core.test_cuda_decode_recovery import RESCUE_COLLAPSED

    audio, _, _ = decode
    engine = Engine([[segment(0, 1, "rescued")]], "cpu", "int8")
    other = Engine([], "cpu", "int8")
    monkeypatch.setattr(tr, "MODEL", other if slot_active else engine)
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr._LM_RUNNER, "slot", SimpleNamespace(model=engine, pipeline=None)
                        if slot_active else None, raising=False)
    task = TranscriptionTask(audio)
    task.languages = ("en", "fr") if mixed else None
    wrapped = []
    monkeypatch.setattr(tr, "_two_language_runner", lambda model, pair: wrapped.append((model, pair)) or model)
    samples = np.ones(16000)
    monkeypatch.setattr(na, "_decode_window", lambda *a: samples)
    monkeypatch.setattr(cr, "find_suspect_spans", lambda *a: [object()])
    monkeypatch.setattr(cr, "rescue", lambda data, duration, speech, transcribe, **kw:
                        (transcribe(5, 6), SimpleNamespace(lines=lambda: [], rescued=[], kept=[])))
    result = RESCUE_COLLAPSED(task, [{"start": 0, "end": 3, "text": "original"}], audio,
                             {"batch_size": 16, "clip_timestamps": "5,6", "vad_parameters": {},
                              "word_timestamps": False}, False, "en", 20, None)
    assert [s["text"] for s in result] == ["rescued"]
    assert len(engine.calls) == 1 and other.calls == []
    source, options = engine.calls[0]
    assert source is samples
    assert options == {"word_timestamps": False, "vad_filter": False,
                       "condition_on_previous_text": False, **({} if mixed else {"language": "en"})}
    assert wrapped == ([(engine, ("en", "fr"))] if mixed else [])


@pytest.mark.parametrize("stage", ["detect", "start", "iterate", "language_iterate"])
@pytest.mark.parametrize("message", ["Invalid data found when processing input", "VAD inference failed"])
def test_non_cuda_runtime_error_never_recovers(stage, message):
    error = RuntimeError(message)
    engine = Engine([error] if stage == "start" else [[error]])
    engine.detect_language = lambda **kw: (_ for _ in ()).throw(error)
    retries = []
    runner = WhisperDecode(lambda options: engine, lambda: not retries,
                           lambda options, oom: retries.append(oom), 0,
                           language_check=stage == "language_iterate")
    with pytest.raises(RuntimeError, match=message):
        if stage == "detect":
            runner.detect_language(audio=np.zeros(16000))
        else:
            segments, _ = runner.transcribe(np.zeros(16000))
            list(segments)
    assert retries == []


def test_language_detection_oom_keeps_quantized_cuda_retry(decode, monkeypatch):
    audio, _, _ = decode
    engine = Engine([])
    engine.detect_language = lambda **kw: (_ for _ in ()).throw(RuntimeError(OOM))
    quantized = Engine([], compute="int8_float16")
    quantized.detect_language = lambda **kw: ("en", 0.9, [("en", 0.9)])
    monkeypatch.setattr(tr, "MODEL", engine)
    calls = []
    monkeypatch.setattr(tr, "WhisperModel", lambda path, **kw: calls.append(kw) or quantized)
    monkeypatch.setattr(tr, "_wrap_for_batched", lambda model: None)
    assert tr._whisper_runner(TranscriptionTask(audio)).detect_language(audio=np.zeros(16000))[0] == "en"
    assert calls == [{"device": "cuda", "compute_type": "int8_float16"}]


@pytest.mark.parametrize("clips, expected", [("2,6,10,14", [0, 2, 6, 10]),
                                           ([2, 6, 10, 14], [0, 2, 6, 10]),
                                           ("2", [0])])
def test_retry_rebases_clip_timestamps_on_each_slice(clips, expected):
    original = deepcopy(clips)
    engine = Engine([[segment(2, 4, "first"), RuntimeError(OOM)],
                     [segment(0, 2, "second"), RuntimeError(OOM)],
                     [segment(4, 8, "last")]])
    retries = []
    runner = WhisperDecode(lambda options: engine, lambda: True,
                           lambda options, oom: retries.append(oom), 0)
    data = np.arange(20 * 16000)
    segments, _ = runner.transcribe(data, clip_timestamps=clips)
    assert [(s.start, s.end) for s in segments] == [(2, 4), (4, 6), (10, 14)]
    assert len(engine.calls[1][0]) == 16 * 16000
    assert engine.calls[1][1]["clip_timestamps"] == expected
    assert engine.calls[2][1]["clip_timestamps"] == ([4, 8] if len(expected) > 1 else [0])
    assert clips == original


def test_resume_retry_never_rewinds_past_saved_silence(decode, monkeypatch):
    from core import _checkpoint as cp

    audio, _, _ = decode
    task = TranscriptionTask(audio)
    tr._note_run_identity(task)
    tr._write_periodic_checkpoint(task, [{"start": 0, "end": 5, "text": "saved"}], 9, "en", 0.9, None)
    engine = Engine([RuntimeError(OOM)])
    monkeypatch.setattr(tr, "MODEL", engine)

    def load(*a, **kw):
        assert cp.load_checkpoint(audio)["last_end_time"] == 9
        raise RuntimeError("replacement failed")

    monkeypatch.setattr(tr, "WhisperModel", load)
    with pytest.raises(RuntimeError, match="replacement failed"):
        tr.resume_transcription(task)
    assert cp.load_checkpoint(audio)["last_end_time"] == 9


@pytest.mark.parametrize("slot_active", [False, True])
def test_unbatched_recovery_preserves_available_pipeline(decode, monkeypatch, slot_active):
    audio, _, _ = decode
    gpu = Engine([RuntimeError(OOM)])
    replacement = Engine([[segment(0, 1, "recovered")]], compute="int8_float16")
    pipeline = object()
    slot = tr._WhisperLanguageModel("test/model", "fake-model")
    slot.model, slot.pipeline = gpu, object()
    monkeypatch.setattr(tr._LM_RUNNER, "slot", slot if slot_active else None, raising=False)
    monkeypatch.setattr(tr, "MODEL", gpu)
    monkeypatch.setattr(tr, "PIPELINE", object())
    monkeypatch.setattr(tr, "WhisperModel", lambda *a, **kw: replacement)
    monkeypatch.setattr(tr, "_wrap_for_batched", lambda model: pipeline)
    segments, _ = tr._whisper_runner(TranscriptionTask(audio), language_check=True).transcribe("audio")
    assert [s.text for s in segments] == ["recovered"]
    assert (slot.pipeline if slot_active else tr.PIPELINE) is pipeline
    assert replacement.calls[0][1] == {}


def test_failed_iterator_wrapper_is_released_before_reload():
    class Iterator:
        def __iter__(self):
            return self

        def __next__(self):
            raise RuntimeError(OOM)

        def close(self):
            pass

    previous = []

    class Model:
        def transcribe(self, *a, **kw):
            iterator = Iterator() if not previous else iter([])
            if not previous:
                previous.append(weakref.ref(iterator))
            return iterator, SimpleNamespace(language="en")

    def recover(options, oom):
        gc.collect()
        assert previous[0]() is None

    runner = WhisperDecode(lambda options: Model(), lambda: True, recover, 0)
    segments, _ = runner.transcribe(np.zeros(16000))
    assert list(segments) == []


def test_failed_rescue_retry_only_checkpoints_complete_first_pass(decode, monkeypatch):
    from core import _checkpoint as cp, collapse_rescue as cr
    from core.backends import nvidia_asr as na
    from tests.core.test_cuda_decode_recovery import RESCUE_COLLAPSED

    audio, _, _ = decode
    task = TranscriptionTask(audio)
    tr._note_run_identity(task)
    data = [{"start": 0, "end": 20, "text": "complete first pass"}]
    engine = Engine([[segment(0, 1, "unfinished rescue"), RuntimeError(OOM)]])
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(na, "_decode_window", lambda *a: np.zeros(5 * 16000))
    monkeypatch.setattr(cr, "find_suspect_spans", lambda *a: [object()])

    def rescue(data, duration, speech, transcribe, **kw):
        transcribe(0, 5)
        pytest.fail("the failed rescue must not finish")

    def load(*a, **kw):
        checkpoint = cp.load_checkpoint(audio)
        assert checkpoint["transcription_completed"]
        assert checkpoint["segments"] == data
        raise RuntimeError("replacement failed")

    monkeypatch.setattr(cr, "rescue", rescue)
    monkeypatch.setattr(tr, "WhisperModel", load)
    assert RESCUE_COLLAPSED(task, data, audio, {}, False, "en", 20, None) == data
    assert cp.load_checkpoint(audio)["segments"] == data


@pytest.mark.parametrize("load_method", ["load_existing", "load"])
@pytest.mark.parametrize("different_model", [False, True])
def test_backend_recovery_state_belongs_to_loaded_model(monkeypatch, tmp_path, load_method, different_model):
    from core.backends import faster_whisper_be as fw

    backend = fw.FasterWhisperBackend()
    backend._model_path = str(tmp_path / "old") if different_model else str(tmp_path)
    backend._downgraded = True
    backend._decode_batch_size = 1
    backend._device, backend._compute_type, backend._requested_device = "cpu", "int8", "cuda"
    monkeypatch.setattr(fw, "load_config", lambda **kw: {"model_path": str(tmp_path)})
    monkeypatch.setattr(fw, "ensure_model", lambda *a: str(tmp_path))
    monkeypatch.setattr(fw, "_detect_device", lambda cfg: ("cuda", "float16"))
    calls = []

    def load(path, status_cb):
        backend._model_path = path
        calls.append((backend._device, backend._compute_type))

    monkeypatch.setattr(backend, "_load_self_healing", load)
    assert getattr(backend, load_method)()
    assert calls == ([("cuda", "float16")] if different_model else [("cpu", "int8")])
    assert backend._downgraded is (not different_model)
    assert backend._decode_batch_size == (0 if different_model else 1)


def test_backend_unload_clears_decode_recovery_state():
    from core.backends.faster_whisper_be import FasterWhisperBackend

    backend = FasterWhisperBackend()
    backend._downgraded, backend._decode_batch_size = True, 1
    backend.unload()
    assert not backend.downgraded and backend._decode_batch_size == 0


@pytest.mark.parametrize("release", ["default", "language"])
def test_legacy_unload_clears_decode_recovery_state(decode, monkeypatch, release):
    monkeypatch.setattr(tr, "MODEL", object())
    monkeypatch.setattr(tr, "_CUDA_BATCH_SIZE", 1)
    monkeypatch.setattr(tr, "_DEVICE_DOWNGRADED", True)
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "compute_type", "int8")
    monkeypatch.setattr(tr, "detect_device", lambda: ("cuda", "float16"))
    if release == "default":
        assert tr.release_default_model()
    else:
        tr._WhisperLanguageModel("model", "folder").unload()
    assert tr._CUDA_BATCH_SIZE == 0 and not tr._DEVICE_DOWNGRADED
    assert (tr.device, tr.compute_type) == ("cuda", "float16")


def test_legacy_fresh_model_load_clears_batch_cap_and_cpu_fallback(decode, monkeypatch):
    from core import hardware

    monkeypatch.setattr(tr, "_CUDA_BATCH_SIZE", 1)
    monkeypatch.setattr(tr, "_DEVICE_DOWNGRADED", True)
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "compute_type", "int8")
    monkeypatch.setattr(tr, "detect_device", lambda: ("cuda", "float16"))
    monkeypatch.setattr(hardware, "prepare_cuda_runtime", lambda: None)
    monkeypatch.setattr(hardware, "warm_up_cuda_model", lambda model: None)
    calls = []
    monkeypatch.setattr(tr, "WhisperModel", lambda path, **kw: calls.append((path, kw)) or object())
    tr._load_whisper_model_self_healing("smaller-model", tr.device, tr.compute_type)
    assert calls == [("smaller-model", {"device": "cuda", "compute_type": "float16"})]
    assert tr._CUDA_BATCH_SIZE == 0 and not tr._DEVICE_DOWNGRADED


def test_nvidia_first_oom_collects_and_empties_cache_before_retry(monkeypatch):
    from core.backends import nvidia_asr as na

    backend = na.NvidiaAsrBackend()
    backend._device = "cuda"
    events = []
    monkeypatch.setattr(na.gc, "collect", lambda: events.append("collect"))
    torch = SimpleNamespace(cuda=SimpleNamespace(empty_cache=lambda: events.append("empty")))
    monkeypatch.setattr(na, "_import_torch_and_transformers", lambda: (torch, None))

    def run(audio):
        events.append("run")
        if len(events) == 1:
            raise RuntimeError(OOM)
        assert events[:4] == ["run", "collect", "empty", "run"]
        return "text"

    assert len(list(backend._decode_audio_parts(np.zeros(4 * na.TARGET_SR), run, None))) == 2


def test_nvidia_cpu_fallback_drops_gpu_piece_cap(monkeypatch):
    from core.backends import nvidia_asr as na

    backend = na.NvidiaAsrBackend()
    backend._device = "cuda"
    backend._runner = lambda audio: "cpu text"
    monkeypatch.setattr(na, "_import_torch_and_transformers", lambda: (SimpleNamespace(float32="f32"), None))
    monkeypatch.setattr(na, "_build_rnnt", lambda *a: backend._runner)
    calls = []

    def run(audio):
        calls.append((backend._device, len(audio)))
        if backend._device == "cuda":
            raise RuntimeError(OOM)
        return "text"

    assert len(list(backend._decode_audio_parts(np.zeros(4 * na.TARGET_SR), run, None))) == 1
    assert calls == [("cuda", 4 * na.TARGET_SR), ("cuda", 2 * na.TARGET_SR), ("cpu", 4 * na.TARGET_SR)]
    assert backend._cuda_max_samples == 0


@pytest.mark.parametrize("unload", [False, True])
def test_nvidia_lifecycle_clears_recovery_state(monkeypatch, unload):
    from core.backends import nvidia_asr as na

    backend = na.NvidiaAsrBackend(config={"nvidia_asr_model_id": "new/model"})
    backend._cpu_fallback, backend._cuda_max_samples = True, 16000
    if unload:
        backend.unload()
    else:
        monkeypatch.setattr(backend, "prepare_engine", lambda *a: True)
        monkeypatch.setattr(na, "recipe_for", lambda *a: None)
        monkeypatch.setattr(na, "_import_torch_and_transformers", lambda: (
            SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), float16="f16"), None))
        monkeypatch.setattr(na, "_build_pipeline", lambda *a: object())
        assert backend.load()
        assert backend.device == "cuda"
    assert not backend._cpu_fallback and backend._cuda_max_samples == 0


def test_nvidia_cancelled_pipeline_window_does_not_report_complete(monkeypatch):
    from core.backends import nvidia_asr as na

    backend = na.NvidiaAsrBackend()
    backend._ready = True
    backend._supports_word_ts = False
    stopped = []

    def infer(*a, **kw):
        stopped.append(True)
        return {"text": "partial"}

    backend._pipe = infer
    monkeypatch.setattr(na, "_decode_window", lambda *a: np.zeros(16000))
    monkeypatch.setattr(na, "plan_chunks", lambda *a: [(0, 1)])
    progress = []
    backend.transcribe_to_segments("input.wav", duration=1, progress_cb=progress.append,
                                   cancelled=lambda: bool(stopped))
    assert progress == []
