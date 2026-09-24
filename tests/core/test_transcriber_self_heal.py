"""Tests for the R3 self-healing CUDA->CPU model load in ``core.transcriber``.

When ``WhisperModel(device="cuda", ...)`` raises (the classic missing
cuDNN/cuBLAS runtime), the load must NOT hard-fail with a bogus re-download
prompt — it should log the reason, retry with ("cpu","int8"), flip the
downgrade flag, and report the effective device. We stub WhisperModel so no
real model/CUDA stack is needed.
"""
from __future__ import annotations

import sys
import types

import pytest


@pytest.fixture
def transcriber(monkeypatch):
    """Import core.transcriber with WhisperModel stubbed."""
    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t
    return t


class _FakeCt2:
    """Stand-in for the underlying CTranslate2 object exposing device info."""

    def __init__(self, device: str, compute_type: str) -> None:
        self.device = device
        self.compute_type = compute_type


class _FakeWhisperModel:
    """WhisperModel stub: raises on cuda, succeeds on cpu."""

    def __init__(self, model_path, device="cpu", compute_type="int8"):
        if device == "cuda":
            raise RuntimeError(
                "Library cudnn_ops_infer64_8.dll is not found or cannot be loaded"
            )
        self.model = _FakeCt2(device, compute_type)


def test_self_heal_downgrades_to_cpu_on_cuda_failure(transcriber, monkeypatch):
    monkeypatch.setattr(transcriber, "WhisperModel", _FakeWhisperModel)
    msgs: list[str] = []
    model = transcriber._load_whisper_model_self_healing(
        "/fake/model", "cuda", "float16", msgs.append
    )
    assert model is not None
    eff = transcriber.get_effective_device()
    assert eff.downgraded is True
    assert eff.device == "cpu"
    assert eff.compute_type == "int8"
    assert eff.requested_device == "cuda"
    # The status callback should mention the CPU fallback.
    assert any("CPU" in m for m in msgs)


def test_self_heal_no_downgrade_when_cuda_loads(transcriber, monkeypatch):
    class _OkModel:
        def __init__(self, model_path, device="cpu", compute_type="int8"):
            self.model = _FakeCt2(device, compute_type)

    monkeypatch.setattr(transcriber, "WhisperModel", _OkModel)
    model = transcriber._load_whisper_model_self_healing(
        "/fake/model", "cuda", "float16", None
    )
    assert model is not None
    eff = transcriber.get_effective_device()
    assert eff.downgraded is False
    assert eff.device == "cuda"
    assert eff.compute_type == "float16"


def test_cpu_request_failure_still_raises(transcriber, monkeypatch):
    """A CPU load that fails has nothing to fall back to — it must raise."""
    class _BoomModel:
        def __init__(self, model_path, device="cpu", compute_type="int8"):
            raise RuntimeError("cpu load broke")

    monkeypatch.setattr(transcriber, "WhisperModel", _BoomModel)
    with pytest.raises(RuntimeError, match="cpu load broke"):
        transcriber._load_whisper_model_self_healing(
            "/fake/model", "cpu", "int8", None
        )


def test_load_existing_model_self_heals_and_stays_ready(
    transcriber, monkeypatch, tmp_path
):
    """The full load path: requested cuda, falls back to cpu, MODEL_READY."""
    model_dir = tmp_path / "model"
    model_dir.mkdir()
    monkeypatch.setattr(transcriber, "WhisperModel", _FakeWhisperModel)
    monkeypatch.setattr(transcriber, "config", {
        "transcribe_backend": "faster_whisper",
        "model_path": str(model_dir),
    })
    monkeypatch.setattr(transcriber, "device", "cuda")
    monkeypatch.setattr(transcriber, "compute_type", "float16")
    # No batched pipeline wrap on the downgraded CPU model.
    monkeypatch.setattr(transcriber, "BatchedInferencePipeline", None)

    ok = transcriber.load_existing_model(lambda m: None)
    assert ok is True
    assert transcriber.MODEL_READY is True
    eff = transcriber.get_effective_device()
    assert eff.downgraded is True
    assert eff.device == "cpu"
    # The module global `device` must be updated to the effective device so
    # _wrap_for_batched does not try to wrap a CPU model in a CUDA pipeline.
    assert transcriber.device == "cpu"


def test_get_effective_device_capture_is_getattr_guarded(transcriber, monkeypatch):
    """A WhisperModel whose .model lacks device attrs falls back to requested."""
    class _NoAttrModel:
        def __init__(self, model_path, device="cpu", compute_type="int8"):
            self.model = object()  # no .device / .compute_type

    monkeypatch.setattr(transcriber, "WhisperModel", _NoAttrModel)
    transcriber._load_whisper_model_self_healing("/fake", "cpu", "int8", None)
    eff = transcriber.get_effective_device()
    assert eff.device == "cpu"
    assert eff.compute_type == "int8"


# ---------- GPU warm-up failures self-heal too (issue #7) ------------------------


def _warmup_fails_on_cuda(model):
    """Stand-in for core.hardware.warm_up_cuda_model: CTranslate2 raises the
    first time the GPU really runs (cuBLAS is loaded lazily)."""
    if getattr(getattr(model, "model", None), "device", "") == "cuda":
        raise RuntimeError(
            "CUDA failed with error no kernel image is available for "
            "execution on the device"
        )


def test_self_heal_downgrades_when_the_gpu_warm_up_fails(transcriber, monkeypatch):
    """Construction succeeds but the first GPU pass fails -> CPU, not a
    broken model that dies on the user's first transcription."""
    import core.hardware as hw

    class _OkModel:
        def __init__(self, model_path, device="cpu", compute_type="int8"):
            self.model = _FakeCt2(device, compute_type)

    monkeypatch.setattr(transcriber, "WhisperModel", _OkModel)
    monkeypatch.setattr(hw, "prepare_cuda_runtime", lambda: True)
    monkeypatch.setattr(hw, "warm_up_cuda_model", _warmup_fails_on_cuda)
    msgs: list[str] = []
    transcriber._load_whisper_model_self_healing(
        "/fake/model", "cuda", "float16", msgs.append
    )
    eff = transcriber.get_effective_device()
    assert eff.downgraded is True
    assert eff.device == "cpu"
    # The user-facing status carries the architecture-specific reason.
    assert any("CPU" in m and "brand-new NVIDIA generation" in m for m in msgs)


def test_backend_self_heal_downgrades_when_the_gpu_warm_up_fails(monkeypatch):
    import core.hardware as hw
    from core.backends import faster_whisper_be as be

    class _OkModel:
        def __init__(self, model_path, device="cpu", compute_type="int8"):
            self.model = _FakeCt2(device, compute_type)

    monkeypatch.setattr(be, "WhisperModel", _OkModel)
    monkeypatch.setattr(hw, "prepare_cuda_runtime", lambda: True)
    monkeypatch.setattr(hw, "warm_up_cuda_model", _warmup_fails_on_cuda)
    backend = be.FasterWhisperBackend()
    backend._requested_device = "cuda"
    backend._compute_type = "float16"
    backend._load_self_healing("/fake/model", None)
    assert backend.downgraded is True
    assert backend.device == "cpu"


def test_cuda_load_prepares_the_runtime_before_constructing(transcriber, monkeypatch):
    import core.hardware as hw

    order: list[str] = []

    class _OkModel:
        def __init__(self, model_path, device="cpu", compute_type="int8"):
            order.append(f"construct:{device}")
            self.model = _FakeCt2(device, compute_type)

    monkeypatch.setattr(transcriber, "WhisperModel", _OkModel)
    monkeypatch.setattr(hw, "prepare_cuda_runtime", lambda: order.append("prepare") or True)
    monkeypatch.setattr(hw, "warm_up_cuda_model", lambda m: order.append("warm_up"))
    transcriber._load_whisper_model_self_healing("/fake/model", "cuda", "float16", None)
    assert order == ["prepare", "construct:cuda", "warm_up"]
    assert transcriber.get_effective_device().downgraded is False
