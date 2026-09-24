"""Tests for the R3 CUDA usability gate in ``core.hardware``.

``ctranslate2.get_cuda_device_count()`` only proves a driver + GPU exist; it
does NOT verify the CUDA runtime libraries (cuBLAS) load. When they don't, the
first CUDA forward pass hard-fails. ``cuda_load_ok()`` + the probe gating make
the autodetect refuse CUDA in that state. These tests monkeypatch ctranslate2
and the DLL-loadable probe so no real CUDA stack is needed. The fake exposes
the REAL CTranslate2 API (``get_cuda_device_count``) -- the old fake defined a
``contains_cuda_device`` that no real CTranslate2 has, which hid issue #7;
tests/core/test_hardware_ct2_contract.py checks the real package.
"""
from __future__ import annotations

import sys
import types

import pytest

from core import hardware as hw


def _fake_ct2(monkeypatch, *, has_device: bool):
    fake = types.ModuleType("ctranslate2")
    fake.__version__ = "4.8.2"  # type: ignore[attr-defined]
    fake.get_cuda_device_count = lambda: 1 if has_device else 0  # type: ignore[attr-defined]
    fake.get_supported_compute_types = lambda dev: {"float16", "int8_float16"}  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    return fake


# ---------- cuda_load_ok --------------------------------------------------------


def test_cuda_load_ok_false_when_no_device(monkeypatch):
    _fake_ct2(monkeypatch, has_device=False)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": "/fake/cublas"})
    assert hw.cuda_load_ok() is False


def test_cuda_load_ok_false_when_runtime_dlls_broken(monkeypatch):
    """Device present but cuBLAS not loadable => not ready."""
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None})
    assert hw.cuda_load_ok() is False


def test_cuda_load_ok_true_when_device_and_runtime_ok(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": "/fake/cublas"})
    assert hw.cuda_load_ok() is True


def test_cuda_load_ok_never_raises_when_ct2_absent(monkeypatch):
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    # Importing a None module raises ImportError inside the helper; it must be
    # swallowed and reported as not-ok.
    assert hw.cuda_load_ok() is False


# ---------- _probe_cuda gating --------------------------------------------------


def test_probe_cuda_returns_empty_when_runtime_dlls_broken(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None})
    assert hw._probe_cuda() == []


def test_probe_cuda_returns_tiers_when_runtime_ok(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": "/fake/cublas"})
    monkeypatch.setattr(hw, "_gpu_name", lambda: "RTX 4090")
    tiers = hw._probe_cuda()
    assert tiers and all(t.device == "cuda" for t in tiers)
    assert tiers[0].slug == "cuda_float16"


def test_probe_tiers_falls_back_to_cpu_on_broken_cuda(monkeypatch):
    """End-to-end: a broken-DLL host yields only the CPU tier."""
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None})
    monkeypatch.setattr(hw, "_probe_qnn_npu", lambda: [])
    monkeypatch.setattr(hw, "_probe_openvino", lambda: [])
    monkeypatch.setattr(hw, "_probe_directml", lambda: [])
    tiers = hw.probe_tiers()
    assert [t.slug for t in tiers] == ["cpu_int8"]


# ---------- detect_device_for gating -------------------------------------------


def test_detect_device_for_skips_cuda_when_runtime_broken(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None})
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    # Block the torch legacy fallback so we land on cpu deterministically.
    monkeypatch.setitem(sys.modules, "torch", None)
    dev, ct = hw.detect_device_for({"device": "auto", "compute_type": "int8"})
    assert dev == "cpu"


def test_detect_device_for_uses_cuda_when_runtime_ok(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": "/fake/cublas"})
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    dev, ct = hw.detect_device_for({"device": "auto", "compute_type": "int8"})
    assert dev == "cuda"
    assert ct in ("float16", "int8_float16", "int8")


# ---------- device_choice_from_hardware_file gating ----------------------------


def test_hardware_file_cuda_rejected_when_runtime_broken(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None})
    monkeypatch.setattr(
        hw, "load_hardware_choice",
        lambda: {"device": "cuda", "compute_type": "float16",
                 "backend": "faster_whisper"},
    )
    assert hw.device_choice_from_hardware_file() is None


def test_hardware_file_cuda_accepted_when_runtime_ok(monkeypatch):
    _fake_ct2(monkeypatch, has_device=True)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": "/fake/cublas"})
    monkeypatch.setattr(
        hw, "load_hardware_choice",
        lambda: {"device": "cuda", "compute_type": "float16",
                 "backend": "faster_whisper"},
    )
    assert hw.device_choice_from_hardware_file() == ("cuda", "float16")


def test_probe_tiers_restores_gc_state():
    """Regression for the 2026-08-15 GC-mid-import crash class (see
    core/backends/google_cloud_stt.py); probe_tiers() does the first
    import of ctranslate2/onnxruntime/torch on a background thread
    (app.widgets.hardware_wizard), same risk."""
    import gc
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            hw.probe_tiers()
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


# ---------- classify_cuda_load_failure / cuda_load_failure_reason -------------


@pytest.mark.parametrize(
    "text",
    [
        "CUDA error: no kernel image is available for execution on the device",
        "RuntimeError: invalid device function",
        "NVIDIA GeForce RTX 5060 Laptop GPU with CUDA capability sm_120 is not "
        "compatible with the current PyTorch installation",
        "the current build supports compute capability sm_50 through sm_90",
    ],
)
def test_classify_cuda_load_failure_detects_arch_unsupported(text):
    assert hw.classify_cuda_load_failure(text) == "arch_unsupported"


@pytest.mark.parametrize(
    "text",
    [
        "Library cudnn_ops_infer64_8.dll is not found",
        "Unable to load libcudnn_ops.so.9",
        "could not load library cublas64_12.dll",
        "libcublas.so.12: cannot open shared object file: No such file or directory",
    ],
)
def test_classify_cuda_load_failure_detects_runtime_libs(text):
    assert hw.classify_cuda_load_failure(text) == "runtime_libs"


def test_classify_cuda_load_failure_unknown_for_unrelated_text():
    assert hw.classify_cuda_load_failure("something unexpected") == "unknown"


def test_classify_cuda_load_failure_detects_out_of_memory():
    text = "CUDA failed with error out of memory"
    assert hw.classify_cuda_load_failure(text) == "out_of_memory"
    assert "memory" in hw.cuda_load_failure_reason(text).lower()


def test_cuda_load_failure_reason_mentions_upgrade_for_arch_unsupported():
    reason = hw.cuda_load_failure_reason(
        "CUDA capability sm_120 is not compatible with the current build"
    )
    assert "ctranslate2" in reason.lower()
    assert "or the model is corrupt" in reason.lower()


def test_cuda_load_failure_reason_is_generic_runtime_libs_message_by_default():
    reason = hw.cuda_load_failure_reason("some other unrelated failure")
    assert "cublas" in reason.lower()


def test_probe_tiers_serializes_concurrent_calls():
    """A concurrent caller must block on the shared lock, not race
    through — same contract as the other hardened availability probes."""
    import threading

    from core._gc_import_guard import _lock as guard_lock

    acquired = guard_lock.acquire(timeout=1.0)
    assert acquired, "test setup: could not acquire the lock"
    result: dict[str, bool] = {}

    def call():
        result["done"] = bool(hw.probe_tiers())

    t = threading.Thread(target=call, daemon=True)
    t.start()
    t.join(timeout=0.3)
    try:
        assert t.is_alive(), "probe_tiers() did not block on the lock"
    finally:
        guard_lock.release()
    t.join(timeout=5.0)
    assert not t.is_alive(), "probe_tiers() never returned after unlock"
    assert "done" in result
