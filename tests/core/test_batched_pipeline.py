"""Tests for the BatchedInferencePipeline wrapper + device detection.

These don't load a real model — they exercise the small wrapping logic to
prove the right code path runs for the right device.
"""
from __future__ import annotations

import sys
import types

import core.transcriber as t


def test_wrap_returns_none_on_cpu(monkeypatch):
    monkeypatch.setattr(t, "device", "cpu")
    assert t._wrap_for_batched(object()) is None


def test_wrap_returns_pipeline_on_cuda(monkeypatch):
    monkeypatch.setattr(t, "device", "cuda")

    class FakePipeline:
        def __init__(self, model):
            self.model = model

    monkeypatch.setattr(t, "BatchedInferencePipeline", FakePipeline)
    sentinel = object()
    wrapped = t._wrap_for_batched(sentinel)
    assert isinstance(wrapped, FakePipeline)
    assert wrapped.model is sentinel


def test_wrap_handles_pipeline_constructor_failure(monkeypatch):
    monkeypatch.setattr(t, "device", "cuda")

    class BoomPipeline:
        def __init__(self, model):
            raise RuntimeError("CUDA not really there")

    monkeypatch.setattr(t, "BatchedInferencePipeline", BoomPipeline)
    assert t._wrap_for_batched(object()) is None


def test_wrap_returns_none_when_pipeline_missing(monkeypatch):
    monkeypatch.setattr(t, "device", "cuda")
    monkeypatch.setattr(t, "BatchedInferencePipeline", None)
    assert t._wrap_for_batched(object()) is None


def test_detect_device_works_without_torch(monkeypatch):
    """detect_device must not crash if torch isn't installed."""
    monkeypatch.setattr(t, "config", {"device": "auto", "compute_type": "int8"})

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setitem(sys.modules, "torch", None)  # ImportError on access

    device, ct = t.detect_device()
    assert device == "cpu"
    assert ct == "int8"


def test_vad_parameters_returns_none_when_disabled(monkeypatch):
    monkeypatch.setattr(t, "config", {"vad_enabled": False})
    assert t._vad_parameters() is None


def test_vad_parameters_uses_config_values(monkeypatch):
    monkeypatch.setattr(t, "config", {
        "vad_enabled": True,
        "vad_min_silence_ms": 750,
        "vad_threshold": 0.6,
        "vad_speech_pad_ms": 300,
    })
    params = t._vad_parameters()
    assert params is not None
    assert params["min_silence_duration_ms"] == 750
    assert params["threshold"] == 0.6
    assert params["speech_pad_ms"] == 300
