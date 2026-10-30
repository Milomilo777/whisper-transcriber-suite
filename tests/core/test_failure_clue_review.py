"""Windowless regressions for failure clues at real worker boundaries."""
from __future__ import annotations

import io
import json
import sys
from contextlib import contextmanager, nullcontext
from types import SimpleNamespace

import pytest

from core import failure_clue as clue
from core import transcriber as tr
from core import worker
from tests.core.test_failure_clue import injected
from tests.core.test_worker_error_outputs import _run


def _prepare_transcriber(monkeypatch, config):
    monkeypatch.setattr(tr, "config", config)
    monkeypatch.setattr(tr, "_runtime_overrides_scope", lambda task: nullcontext(config))
    monkeypatch.setattr(tr, "_protect_existing_checkpoint", lambda *args: None)
    monkeypatch.setattr(tr, "_note_run_identity", lambda *args: None)
    monkeypatch.setattr(tr, "_checked_whisper_task", lambda *args: None)
    monkeypatch.setattr(tr, "get_duration", lambda *args: 10.0)
    monkeypatch.setattr(tr, "require_audio_stream", lambda *args: None)


def _model_that_raises(error):
    scope = {"__name__": "faster_whisper.transcribe", "error": error}
    exec("def construct(*args, **kwargs):\n    raise error\n", scope)
    return scope["construct"]


def test_vad_speech_collection_numpy_allocation_at_worker(monkeypatch, capsys):
    import numpy as np

    from core import speech_collect

    message = "Unable to allocate 2.00 GiB for an array with shape (536870912,) and data type float32"

    def fail(_pieces):
        raise MemoryError(message)

    class Engine:
        def transcribe(self, *args, **kwargs):
            assert kwargs["vad_filter"] is True
            collect = speech_collect._make_collect(lambda *args: None)
            collect(np.zeros(2, dtype=np.float32), [{"start": 0, "end": 2}])

    _prepare_transcriber(monkeypatch, {"transcribe_backend": "faster_whisper", "vad_filter": True})
    monkeypatch.setattr(tr, "MODEL", Engine())
    monkeypatch.setattr(tr, "MODEL_READY", True)
    monkeypatch.setattr(tr, "PIPELINE", None)
    monkeypatch.setattr(tr, "_ALT_BACKEND", None)
    monkeypatch.setattr(np, "concatenate", fail)
    event = next(e for e in _run(monkeypatch, capsys, tr.transcribe) if e["event"] == "error")
    assert event["failure_site"] == "worker.vad"
    assert event["exception_family"] == "MemoryError"
    assert event["observed_code"] == "numpy_alloc_failed"

    monkeypatch.setattr(np, "concatenate", lambda _: (_ for _ in ()).throw(MemoryError(message + "/private.wav")))
    with pytest.raises(MemoryError) as caught:
        speech_collect.gather_speech(np.zeros(2), [{"start": 0, "end": 2}])
    assert clue.observed_code(caught.value) == "none"
    assert clue.observed_code(injected("unrelated", "run", MemoryError(message))) == "none"


def test_false_return_startup_keeps_model_exception_clue(monkeypatch, capsys, tmp_path):
    model = tmp_path / "model"
    model.mkdir()
    (model / "model.bin").write_bytes(b"weights")
    monkeypatch.setattr(tr, "config", {"transcribe_backend": "faster_whisper", "model_path": str(model)})
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "compute_type", "int8")
    monkeypatch.setattr(tr, "WhisperModel", _model_that_raises(RuntimeError("std::bad_alloc")))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    assert worker.main() == 1
    event = next(json.loads(line) for line in capsys.readouterr().out.splitlines()
                 if json.loads(line)["event"] == "startup_error")
    assert event["failure_site"] == "worker.model"
    assert event["exception_family"] == "RuntimeError"
    assert event["observed_code"] == "ct2_bad_alloc"
    assert set(tr.get_model_failure_clue()) == set(clue.registry()["fields"])
    monkeypatch.setattr(tr, "config", {"model_path": str(tmp_path / "missing")})
    assert tr.load_existing_model() is False
    assert tr.get_model_failure_clue() == {}


@pytest.mark.parametrize("message,code", [("private model location", "none"), ("std::bad_alloc", "ct2_bad_alloc")])
def test_lazy_default_model_failure_keeps_explicit_cause(monkeypatch, capsys, tmp_path, message, code):
    _prepare_transcriber(monkeypatch, {"transcribe_backend": "faster_whisper", "model_path": str(tmp_path)})
    monkeypatch.setattr(tr, "MODEL", None)
    monkeypatch.setattr(tr, "MODEL_READY", True)
    monkeypatch.setattr(tr, "_ALT_BACKEND", SimpleNamespace())
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "compute_type", "int8")
    monkeypatch.setattr(tr, "WhisperModel", _model_that_raises(MemoryError(message)))
    event = next(e for e in _run(monkeypatch, capsys, tr.transcribe) if e["event"] == "error")
    assert event["failure_site"] == "worker.model"
    assert event["exception_family"] == "MemoryError"
    assert event["observed_code"] == code
    assert "private" not in str({name: event[name] for name in clue.registry()["fields"]})


def test_model_cause_cycles_and_implicit_context_are_safe():
    outer = RuntimeError("outer")
    origin = MemoryError("private")
    outer.__cause__ = origin
    origin.__cause__ = outer
    assert clue.worker_clue(outer, site="worker.model")["exception_family"] == "MemoryError"
    outer.__cause__ = None
    outer.__context__ = origin
    assert clue.worker_clue(outer, site="worker.model")["exception_family"] == "RuntimeError"


def test_startup_clue_failure_cannot_break_error_event(monkeypatch, capsys):
    monkeypatch.setattr(worker, "load_existing_model", lambda _cb: False)
    monkeypatch.setattr(worker, "get_model_failure_clue", lambda: (_ for _ in ()).throw(RuntimeError("diagnostic failed")))
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))
    assert worker.main() == 1
    assert any(json.loads(line)["event"] == "startup_error" for line in capsys.readouterr().out.splitlines())


def test_model_loader_survives_clue_capture_failure(monkeypatch, tmp_path):
    (tmp_path / "model.bin").write_bytes(b"weights")
    monkeypatch.setattr(tr, "config", {"model_path": str(tmp_path)})
    monkeypatch.setattr(tr, "device", "cpu")
    monkeypatch.setattr(tr, "WhisperModel", _model_that_raises(RuntimeError("std::bad_alloc")))
    monkeypatch.setattr(clue, "worker_clue", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("diagnostic failed")))
    assert tr.load_existing_model() is False
    assert tr.get_model_error() == "std::bad_alloc"
    assert tr.get_model_failure_clue() == {}


def test_nvidia_ready_and_failed_job_report_actual_device(monkeypatch, capsys):
    from core import backends
    from core.backends import nvidia_asr

    config = {"transcribe_backend": "nvidia_asr", "nvidia_asr_device": "cpu"}
    backend = nvidia_asr.NvidiaAsrBackend(config)
    _prepare_transcriber(monkeypatch, config)
    monkeypatch.setattr(tr, "device", "cuda")
    monkeypatch.setattr(tr, "compute_type", "float16")
    monkeypatch.setattr(tr, "_ALT_BACKEND", None)
    monkeypatch.setattr(backends, "get_backend", lambda _name: backend)
    monkeypatch.setattr(backend, "prepare_engine", lambda *args: True)
    torch = SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: True), float32="float32")
    monkeypatch.setattr(nvidia_asr, "_import_torch_and_transformers", lambda: (torch, object()))
    monkeypatch.setattr(nvidia_asr, "_build_pipeline", lambda *args: object())
    monkeypatch.setattr(backend, "transcribe_to_segments", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("failed")))
    inputs = json.dumps({"action": "transcribe", "file_path": "input.wav"}) + "\n" + json.dumps({"action": "shutdown"}) + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO(inputs))

    assert worker.main() == 0
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert next(e for e in events if e["event"] == "ready")["device"] == "cpu"
    error = next(e for e in events if e["event"] == "error")
    assert error["message"] == "failed" and error["failure_site"] == "worker.segments"
    assert error["device"] == "cpu"


def test_unavailable_backend_device_stays_unknown(monkeypatch):
    from app.services.transcription_service import _remember_failure_clue

    monkeypatch.setattr(tr, "config", {"transcribe_backend": "cloud_stt"})
    monkeypatch.setattr(tr, "_ALT_BACKEND", SimpleNamespace())
    monkeypatch.setattr(tr, "device", "cuda")
    assert tr.get_effective_device().device == "unknown"
    task = SimpleNamespace()
    _remember_failure_clue(task, {"device": "cuda"}, event={"device": "unknown"})
    assert task.failure_clue["device"] == "unknown"
    _remember_failure_clue(task, {"device": "cuda"}, event={})
    assert task.failure_clue["device"] == "cuda"


def test_per_file_whisper_device_survives_backend_override_scope(monkeypatch, capsys):
    startup = {"transcribe_backend": "nvidia_asr"}
    per_file = {"transcribe_backend": "faster_whisper"}
    _prepare_transcriber(monkeypatch, startup)

    @contextmanager
    def override(_task):
        tr.config = per_file
        try:
            yield per_file
        finally:
            tr.config = startup

    class Engine:
        def transcribe(self, *args, **kwargs):
            raise RuntimeError("failed")

    monkeypatch.setattr(tr, "_runtime_overrides_scope", override)
    monkeypatch.setattr(tr, "_ALT_BACKEND", SimpleNamespace(device="cpu"))
    monkeypatch.setattr(tr, "_ALT_BACKEND_NAME", "nvidia_asr")
    monkeypatch.setattr(tr, "_EFFECTIVE_DEVICE", "cuda")
    monkeypatch.setattr(tr, "MODEL", Engine())
    monkeypatch.setattr(tr, "MODEL_READY", True)
    monkeypatch.setattr(tr, "PIPELINE", None)
    events = _run(monkeypatch, capsys, tr.transcribe)
    assert next(e for e in events if e["event"] == "ready")["device"] == "cpu"
    assert next(e for e in events if e["event"] == "error")["device"] == "cuda"


def test_backend_device_accessors_and_cuda_index(monkeypatch):
    from core.backends.mlx_whisper_be import MlxWhisperBackend
    from core.backends.nvidia_asr import NvidiaAsrBackend
    from core.backends.whisper_cpp import WhisperCppBackend

    nvidia = NvidiaAsrBackend({"nvidia_asr_device": "cuda:1"})
    assert nvidia.device == "unknown"
    nvidia._ready, nvidia._device = True, "cuda:1"
    monkeypatch.setattr(tr, "config", {"transcribe_backend": "nvidia_asr"})
    monkeypatch.setattr(tr, "_ALT_BACKEND", nvidia)
    monkeypatch.setattr(tr, "_ALT_BACKEND_NAME", "nvidia_asr")
    assert tr.get_effective_device().device == "cuda"
    mlx = MlxWhisperBackend()
    assert mlx.device == "unknown"
    mlx._ready = True
    assert mlx.device == "mlx"
    assert WhisperCppBackend().device == "unknown"


def test_default_device_is_unknown_before_a_model_is_loaded(monkeypatch):
    monkeypatch.setattr(tr, "config", {"transcribe_backend": "faster_whisper"})
    monkeypatch.setattr(tr, "_EFFECTIVE_DEVICE", "")
    monkeypatch.setattr(tr, "device", "cuda")
    assert tr.get_effective_device().device == "unknown"


@pytest.mark.parametrize("library,code", [
    ("cudnn_ops_infer64_8.dll", "cudnn_missing"),
    ("cudnn_cnn_train64_8.dll", "cudnn_missing"),
    ("cudnn_ops64_9.dll", "cudnn_missing"),
    ("libcudnn_ops_infer.so.8", "cudnn_missing"),
    ("libcublas.so.12", "cublas_missing"),
    ("libcublasLt.so.12", "cublas_missing"),
])
def test_missing_cuda_component_messages_are_anchored(library, code):
    message = f"Library {library} is not found or cannot be loaded"
    assert clue.observed_code(injected("faster_whisper.transcribe", "run", RuntimeError(message))) == code
    assert clue.observed_code(RuntimeError(message)) == "none"
    for hostile in ("prefix " + message, message + "/private.wav", "Library C:/private/" + library + " is not found or cannot be loaded"):
        assert clue.observed_code(injected("faster_whisper.transcribe", "run", RuntimeError(hostile))) == "none"


def test_missing_cuda_component_rejects_unrecognised_names():
    message = "Library cudnn_private64_8.dll is not found or cannot be loaded"
    assert clue.observed_code(injected("faster_whisper.transcribe", "run", RuntimeError(message))) == "none"
