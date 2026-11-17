"""Free-memory batch selection and OOM ladders use no real GPU."""
from types import SimpleNamespace

import numpy as np
import pytest

from core import hardware as hw, transcriber as tr
from core.task import TranscriptionTask
from core.backends.faster_whisper_be import FasterWhisperBackend


@pytest.fixture
def setup(monkeypatch):
    engine = SimpleNamespace(model=SimpleNamespace(device_index=[0]))
    monkeypatch.setattr(tr, "MODEL", engine)
    monkeypatch.setattr(tr, "PIPELINE", engine)
    monkeypatch.setattr(tr, "device", "cuda")
    monkeypatch.setattr(tr, "_CUDA_BATCH_SIZE", 0)
    monkeypatch.setattr(tr._LM_RUNNER, "slot", None, raising=False)
    return engine


@pytest.mark.parametrize("free,expected", [(0, 1), (1024, 1), (4096, 8), (8192, 16), (None, 16)])
@pytest.mark.parametrize("backend", [False, True])
def test_free_memory_caps_batch(setup, monkeypatch, free, expected, backend):
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: free, raising=False)
    calls = []
    setup.transcribe = lambda audio, **kw: (calls.append(kw) or iter(()), SimpleNamespace())
    if backend:
        be = FasterWhisperBackend()
        be._model = be._pipeline = setup
        be._device, be._ready = "cuda", True
        be.transcribe_to_segments("unused", vad_parameters={})
    else:
        runner = tr._whisper_runner(TranscriptionTask("unused"), batched=True)
        runner.transcribe(np.zeros(10), batch_size=16)
    assert calls[0]["batch_size"] == expected


def test_second_worker_reads_current_free_memory(setup, monkeypatch):
    free = iter([8192, 4096])
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: next(free), raising=False)
    calls = []
    setup.transcribe = lambda audio, **kw: (calls.append(kw) or iter(()), SimpleNamespace())
    for _ in range(2):
        tr._whisper_runner(TranscriptionTask("unused"), batched=True).transcribe(np.zeros(1), batch_size=16)
    assert [kw["batch_size"] for kw in calls] == [16, 8]


@pytest.mark.parametrize("backend", [False, True])
def test_oom_halving_ladder(setup, monkeypatch, backend):
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: None, raising=False)
    calls = []
    def transcribe(audio, **kw):
        calls.append(kw["batch_size"])
        if len(calls) < 5:
            raise RuntimeError("CUDA out of memory")
        return iter(()), SimpleNamespace()
    setup.transcribe = transcribe
    if backend:
        be = FasterWhisperBackend()
        be._model = be._pipeline = setup
        be._device, be._ready = "cuda", True
        be.transcribe_to_segments("unused", vad_parameters={})
    else:
        task = TranscriptionTask("unused")
        tr._whisper_runner(task, batched=True).transcribe(np.zeros(1), batch_size=16)
        assert task._telemetry_recovery == "cuda_batch_reduced"
    assert calls == [16, 8, 4, 2, 1]


@pytest.mark.parametrize("configured", [1, 3, 7])
def test_configured_batch_is_upper_bound(setup, monkeypatch, configured):
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: 8192)
    assert hw.cuda_batch_size(configured, setup) == configured


@pytest.mark.parametrize("indices", [[2], 2, [], [0, 1], None])
def test_probe_uses_loaded_device_or_preserves_unknown(setup, monkeypatch, indices):
    setup.model.device_index = indices
    seen = []
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: seen.append(index) or 4096)
    expected = 8 if indices in ([2], 2) else 16
    assert hw.cuda_batch_size(16, setup) == expected
    assert seen == ([2] if expected == 8 else [])


@pytest.mark.parametrize("device,batched", [("cpu", True), ("cuda", False)])
def test_non_cuda_or_unbatched_skips_probe(setup, monkeypatch, device, batched):
    monkeypatch.setattr(tr, "device", device)
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: pytest.fail("unexpected probe"))
    setup.transcribe = lambda audio, **kw: (iter(()), SimpleNamespace())
    tr._whisper_runner(TranscriptionTask("unused"), batched=batched).transcribe(np.zeros(1), batch_size=16)


@pytest.mark.parametrize("failure", [None, "retain", "push", "memory", "exception", "invalid"])
def test_driver_probe_balances_context_and_handles_failure(monkeypatch, failure):
    events = []
    class Driver:
        def cuInit(self, flags):
            return 0
        def cuDeviceGet(self, out, ordinal):
            assert ordinal == 2
            out._obj.value = 2
            return 0
        def cuDevicePrimaryCtxRetain(self, out, device):
            events.append("retain")
            out._obj.value = 123
            return int(failure == "retain")
        def cuCtxPushCurrent_v2(self, context):
            assert context.value == 123
            events.append("push")
            return int(failure == "push")
        def cuMemGetInfo_v2(self, free, total):
            events.append("memory")
            if failure == "exception":
                raise OSError("driver unavailable")
            free._obj.value = 4096 * 1024 * 1024
            total._obj.value = (2048 if failure == "invalid" else 8192) * 1024 * 1024
            return int(failure == "memory")
        def cuCtxPopCurrent_v2(self, out):
            events.append("pop")
            return 0
        def cuDevicePrimaryCtxRelease_v2(self, device):
            events.append("release")
            return 0
    monkeypatch.setattr(hw, "_cuda_driver_library", lambda: Driver())
    assert hw.cuda_free_memory_mb(2) == (4096 if failure is None else None)
    assert events == (["retain"] if failure == "retain" else
                      ["retain", "push", "release"] if failure == "push" else
                      ["retain", "push", "memory", "pop", "release"])


def test_missing_driver_preserves_batch(monkeypatch):
    monkeypatch.setattr(hw, "_cuda_driver_library", lambda: None)
    assert hw.cuda_free_memory_mb() is None


def test_batch_choice_logs_basis(setup, monkeypatch, caplog):
    monkeypatch.setattr(hw, "cuda_free_memory_mb", lambda index=0: 4096)
    with caplog.at_level("INFO", logger="core.hardware"):
        assert hw.cuda_batch_size(16, setup) == 8
    assert "CUDA batch size 8 (configured 16; free VRAM 4096 MiB)" in caplog.text
