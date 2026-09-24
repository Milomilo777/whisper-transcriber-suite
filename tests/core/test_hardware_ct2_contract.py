"""Contract tests: core.hardware against the REAL ctranslate2 / faster_whisper.

GitHub issue #7 regression guard. Up to v1.9.1, core/hardware.py called
``ctranslate2.contains_cuda_device()``, which no released CTranslate2 has.
The AttributeError was swallowed, so CUDA read as "absent" on every machine,
and the unit tests never noticed: every one of them swapped ctranslate2 for a
fake module that happened to define that function. These tests use the real
installed packages (skipped only where they are not installed), so an API the
code relies on that the real package lacks fails here, not on users' GPUs.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from core import hardware as hw

_HARDWARE_SRC = Path(hw.__file__).read_text(encoding="utf-8")


def _module_attrs_used(source: str, names: set[str]) -> set[str]:
    """Attribute names accessed directly as ``<name>.<attr>`` in ``source``."""
    used: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in names
        ):
            used.add(node.attr)
    return used


def test_every_ctranslate2_attribute_core_hardware_uses_exists():
    ct2 = pytest.importorskip("ctranslate2")
    used = _module_attrs_used(_HARDWARE_SRC, {"ctranslate2", "ct2"})
    assert "get_supported_compute_types" in used  # the scan itself works
    missing = sorted(a for a in used if not hasattr(ct2, a))
    assert not missing, (
        f"core/hardware.py uses ctranslate2 attributes the installed "
        f"CTranslate2 {ct2.__version__} does not have: {missing}"
    )


def test_device_count_helper_uses_the_real_api():
    ct2 = pytest.importorskip("ctranslate2")
    assert callable(getattr(ct2, "get_cuda_device_count", None))
    count = hw._ct2_cuda_device_count(ct2)
    assert isinstance(count, int) and count >= 0
    assert count == ct2.get_cuda_device_count()


def test_contains_cuda_device_is_only_ever_reached_through_getattr():
    """The name that caused issue #7 may appear only as a getattr fallback."""
    used = _module_attrs_used(_HARDWARE_SRC, {"ctranslate2", "ct2"})
    assert "contains_cuda_device" not in used


def test_ct2_version_parses_the_real_version():
    ct2 = pytest.importorskip("ctranslate2")
    version = hw._ct2_version(ct2)
    assert len(version) >= 2 and version >= (3,)


def test_cuda_status_on_the_real_host_never_raises():
    pytest.importorskip("ctranslate2")
    status = hw.cuda_status()
    assert isinstance(status, hw.CudaStatus)
    if status.usable:
        assert status.gpu_present and status.compute_types
    else:
        assert status.reason


def test_diagnostics_report_runs_on_the_real_host():
    report = hw.diagnostics_report()
    assert "CTranslate2" in report
    assert "CUDA usable:" in report


def test_warm_up_uses_real_faster_whisper_api():
    """warm_up_cuda_model builds its input with these; a rename upstream must
    fail here rather than silently skipping the GPU warm-up."""
    audio = pytest.importorskip("faster_whisper.audio")
    fw = pytest.importorskip("faster_whisper")
    assert callable(getattr(audio, "pad_or_trim", None))
    model_cls = getattr(fw, "WhisperModel")
    assert callable(getattr(model_cls, "encode", None))
    import inspect
    assert "self.feature_extractor" in inspect.getsource(model_cls.__init__)
