"""``detect_device_for`` must always return a usable ``compute_type``.

The returned pair flows straight into ``WhisperModel(device=..., compute_type=...)``
(core/transcriber.py: ``WhisperModel(model_path, device=req_device,
compute_type=req_compute)``). CTranslate2 raises ``TypeError`` for a ``None``
compute type and ``ValueError: Invalid compute type:`` for an empty string,
and ``deep_merge_dicts`` keeps a hand-edited ``"compute_type": null`` or
``""`` in config.json verbatim, so the value can reach the picker as-is.
The device side of the same function already normalizes blank values
(``str(config.get("device") or "auto")``); the compute type must not be
able to come out blank.
"""
from __future__ import annotations

import pytest

from core import hardware as hw


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_an_explicit_device_never_gets_a_blank_compute_type(bad):
    got = hw.detect_device_for({"device": "cpu", "compute_type": bad})
    assert got == ("cpu", "int8")


def test_the_configured_compute_type_is_kept():
    assert hw.detect_device_for(
        {"device": "cpu", "compute_type": "float16"}
    ) == ("cpu", "float16")


def test_the_cpu_fallback_never_gets_a_blank_compute_type(monkeypatch):
    """``device: auto`` with no usable GPU ends on the CPU fallback branch,
    which reads the same config key."""
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(
        hw, "cuda_status",
        lambda: hw.CudaStatus(usable=False, gpu_present=False),
    )
    for bad in (None, "", "   "):
        assert hw.detect_device_for({"device": "auto", "compute_type": bad}) == (
            "cpu", "int8",
        )


def test_a_missing_compute_type_key_still_defaults(monkeypatch):
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(
        hw, "cuda_status",
        lambda: hw.CudaStatus(usable=False, gpu_present=False),
    )
    assert hw.detect_device_for({"device": "cpu"}) == ("cpu", "int8")
    assert hw.detect_device_for({"device": "auto"}) == ("cpu", "int8")
