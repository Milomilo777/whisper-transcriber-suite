"""CUDA runtime discovery, CudaStatus reasons and the GPU warm-up (issue #7).

Hermetic: the library loader, the NVIDIA driver query and ctranslate2 are all
stubbed, so these run the same on a machine with or without an NVIDIA GPU.
"""
from __future__ import annotations

import os
import sys
import types
from typing import Any

import pytest

from core import hardware as hw
from core import optional_deps


def _fake_ct2(monkeypatch, *, count: int = 1, version: str = "4.8.2",
              types_: tuple[str, ...] = ("float16", "int8_float16")):
    fake = types.ModuleType("ctranslate2")
    fake.__version__ = version  # type: ignore[attr-defined]
    fake.get_cuda_device_count = lambda: count  # type: ignore[attr-defined]
    fake.get_supported_compute_types = lambda _d: set(types_)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake)
    return fake


def _fake_driver(monkeypatch, *, name: str = "NVIDIA GeForce RTX 5060 Laptop GPU",
                 cc: tuple[int, int] = (12, 0), driver_version: int = 13040):
    info = {"driver_version": driver_version,
            "gpus": [{"name": name, "cc": cc, "memory_mb": 8151}]}
    monkeypatch.setattr(hw, "_cuda_driver_info", lambda: info)
    monkeypatch.setattr(hw, "sys", _PlatformSys("win32"))


class _PlatformSys:
    """``sys`` stand-in that only overrides ``platform`` (for the darwin
    short-circuit and the Windows file names)."""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def __getattr__(self, name: str) -> Any:
        return getattr(sys, name)


# ---------- which libraries each CTranslate2 build needs -------------------------


@pytest.mark.parametrize(
    "version, expected",
    [
        ((4, 8, 2), {"cuBLAS": ("cublas64_12.dll",)}),
        ((4, 6, 3), {"cuBLAS": ("cublas64_12.dll",)}),
        ((4, 6, 2), {"cuBLAS": ("cublas64_12.dll",), "cuDNN": ("cudnn_ops64_9.dll",)}),
        ((4, 4, 0), {"cuBLAS": ("cublas64_12.dll",), "cuDNN": ("cudnn_ops_infer64_8.dll",)}),
        ((3, 24, 0), {"cuBLAS": ("cublas64_11.dll",), "cuDNN": ("cudnn_ops_infer64_8.dll",)}),
        ((), {"cuBLAS": ("cublas64_12.dll",)}),
    ],
)
def test_required_libs_follow_the_ctranslate2_version_on_windows(monkeypatch, version, expected):
    monkeypatch.setattr(hw, "sys", _PlatformSys("win32"))
    assert hw._required_cuda_libs(version) == expected


def test_required_libs_use_sonames_on_linux(monkeypatch):
    monkeypatch.setattr(hw, "sys", _PlatformSys("linux"))
    assert hw._required_cuda_libs((4, 8, 2)) == {"cuBLAS": ("libcublas.so.12",)}


# ---------- where the libraries are looked for ------------------------------------


def test_pip_wheel_dir_is_preferred_and_torch_lib_is_a_fallback(monkeypatch, tmp_path):
    extras = tmp_path / "pylibs"
    wheel_dir = extras / "nvidia" / "cublas" / "lib"
    wheel_dir.mkdir(parents=True)
    site = tmp_path / "site"
    torch_lib = site / "torch" / "lib"
    torch_lib.mkdir(parents=True)
    monkeypatch.setattr(hw, "sys", _PlatformSys("linux"))
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(extras))
    monkeypatch.setattr(sys, "path", [str(site)])
    preferred, fallback = hw._cuda_library_dir_groups()
    assert preferred == [str(wheel_dir)]
    assert str(torch_lib) in fallback


def test_cuda_toolkit_dirs_come_from_cuda_path(monkeypatch, tmp_path):
    toolkit = tmp_path / "CUDA" / "v12.8"
    (toolkit / "bin").mkdir(parents=True)
    monkeypatch.setattr(hw, "sys", _PlatformSys("linux"))
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(tmp_path / "none"))
    monkeypatch.setattr(sys, "path", [])
    monkeypatch.setenv("CUDA_PATH_V12_8", str(toolkit))
    _preferred, fallback = hw._cuda_library_dir_groups()
    assert str(toolkit / "bin") in fallback


def test_load_order_is_wheel_then_search_path_then_fallback(monkeypatch, tmp_path):
    wheel = tmp_path / "wheel"
    wheel.mkdir()
    (wheel / "libcublas.so.12").write_bytes(b"")
    fallback = tmp_path / "torch_lib"
    fallback.mkdir()
    (fallback / "libcublas.so.12").write_bytes(b"")
    tried: list[str] = []

    def _refuse(target: str) -> Any:
        tried.append(target)
        raise OSError("nope")

    monkeypatch.setattr(hw, "_load_library", _refuse)
    errors: list[str] = []
    where = hw._load_first(("libcublas.so.12",), [str(wheel)], [str(fallback)], errors)
    assert where is None
    assert tried == [
        os.path.join(str(wheel), "libcublas.so.12"),
        "libcublas.so.12",
        os.path.join(str(fallback), "libcublas.so.12"),
    ]
    # Files that exist but fail to load are reported for the diagnostics.
    assert len(errors) == 2


def test_found_library_is_recorded_for_the_diagnostics(monkeypatch, tmp_path):
    wheel = tmp_path / "wheel"
    wheel.mkdir()
    lib = wheel / "libcublas.so.12"
    lib.write_bytes(b"")
    monkeypatch.setattr(hw, "_load_library", lambda target: object())
    where = hw._load_first(("libcublas.so.12",), [str(wheel)], [], [])
    assert where == str(lib)
    assert hw._LOADED_CUDA_LIBS["libcublas.so.12"] == str(lib)


def test_windows_dll_dir_is_added_to_path_once(monkeypatch, tmp_path):
    monkeypatch.setattr(hw, "sys", _PlatformSys("win32"))
    monkeypatch.setattr(hw, "_registered_dll_dirs", set())
    monkeypatch.setattr(os, "add_dll_directory", lambda d: object(), raising=False)
    monkeypatch.setenv("PATH", "C:\\Windows")
    hw._add_to_dll_search_path(str(tmp_path))
    hw._add_to_dll_search_path(str(tmp_path))
    parts = os.environ["PATH"].split(os.pathsep)
    assert parts[0] == str(tmp_path)
    assert parts.count(str(tmp_path)) == 1


# ---------- cuda_status: one reason per broken link --------------------------------


def test_status_names_the_missing_cublas_and_offers_the_install(monkeypatch):
    _fake_ct2(monkeypatch)
    _fake_driver(monkeypatch)
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: False)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None})
    status = hw.cuda_status()
    assert not status.usable and status.gpu_present
    assert status.gpu_name == "NVIDIA GeForce RTX 5060 Laptop GPU"
    assert status.missing_libs == ("cublas64_12.dll",)
    assert status.can_install_runtime is True
    assert "cublas64_12.dll" in status.reason
    assert "Install GPU support" in status.fix


def test_status_does_not_offer_install_when_old_engine_also_needs_cudnn(monkeypatch):
    _fake_ct2(monkeypatch, version="4.5.0")
    _fake_driver(monkeypatch)
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: False)
    monkeypatch.setattr(
        hw, "_cuda_runtime_report", lambda v=None: {"cuBLAS": None, "cuDNN": None},
    )
    status = hw.cuda_status()
    assert status.can_install_runtime is False
    assert "nvidia-cudnn-cu12" in status.fix


def test_status_reports_a_stalled_loader(monkeypatch):
    _fake_ct2(monkeypatch)
    _fake_driver(monkeypatch)
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: False)
    monkeypatch.setattr(hw, "_cuda_runtime_report", lambda v=None: None)
    status = hw.cuda_status()
    assert not status.usable and "did not finish" in status.reason


def test_status_blames_an_old_driver(monkeypatch):
    _fake_ct2(monkeypatch, count=0)
    _fake_driver(monkeypatch, driver_version=11080)
    status = hw.cuda_status()
    assert status.gpu_present and not status.usable
    assert "too old" in status.reason and "11.8" in status.reason


def test_status_when_driver_sees_gpu_but_engine_does_not(monkeypatch):
    _fake_ct2(monkeypatch, count=0)
    _fake_driver(monkeypatch)
    status = hw.cuda_status()
    assert status.gpu_present and not status.usable
    assert "RTX 5060" in status.reason


def test_status_no_gpu_at_all_is_not_actionable(monkeypatch):
    _fake_ct2(monkeypatch, count=0)
    monkeypatch.setattr(hw, "_cuda_driver_info", lambda: {})
    monkeypatch.setattr(hw, "sys", _PlatformSys("linux"))
    status = hw.cuda_status()
    assert status.gpu_present is False and status.usable is False


def test_usable_blackwell_gpu_gets_the_first_run_note(monkeypatch):
    _fake_ct2(monkeypatch, types_=("float16",))
    _fake_driver(monkeypatch, cc=(12, 0))
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: True)
    status = hw.cuda_status()
    assert status.usable and status.compute_capability == "12.0"
    assert "first GPU run" in status.note
    tiers = hw._probe_cuda()
    assert [t.slug for t in tiers] == ["cuda_float16"]
    assert "RTX 5060" in tiers[0].label


def test_ada_gpu_needs_no_first_run_note(monkeypatch):
    _fake_ct2(monkeypatch)
    _fake_driver(monkeypatch, name="NVIDIA GeForce RTX 4070", cc=(8, 9))
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: True)
    assert hw.cuda_status().note == ""


def test_macos_never_reports_cuda(monkeypatch):
    monkeypatch.setattr(hw, "sys", _PlatformSys("darwin"))
    status = hw.cuda_status()
    assert status.usable is False and status.gpu_present is False


def test_cuda_status_never_raises(monkeypatch):
    def _boom():
        raise RuntimeError("driver exploded")

    monkeypatch.setattr(hw, "_cuda_status", _boom)
    status = hw.cuda_status()
    assert status.usable is False and "driver exploded" in status.reason


def test_detect_device_for_picks_cuda_from_a_usable_status(monkeypatch):
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=True, gpu_present=True, compute_types=("float16", "int8_float16"),
    ))
    assert hw.detect_device_for({"device": "auto"}) == ("cuda", "float16")


def test_detect_device_for_ignores_torch_when_ctranslate2_cannot_use_the_gpu(monkeypatch):
    """A torch that sees the GPU says nothing about CTranslate2 (the engine)."""
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=False, gpu_present=True, reason="cuBLAS missing",
    ))
    fake_torch = types.ModuleType("torch")
    fake_torch.cuda = types.SimpleNamespace(is_available=lambda: True)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    assert hw.detect_device_for({"device": "auto", "compute_type": "int8"}) == ("cpu", "int8")


# ---------- hardware.json written by the old (blind) probe --------------------------


def _write_choice(tmp_path, payload: dict[str, Any]) -> None:
    import json
    (tmp_path / hw.HARDWARE_FILE_NAME).write_text(json.dumps(payload), encoding="utf-8")


def test_cpu_choice_saved_by_the_old_probe_is_re_probed(monkeypatch, tmp_path):
    """v1.9.1 and older could never offer CUDA, so their saved CPU pick is
    not a preference -- it must not pin a now-detectable GPU to the CPU."""
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    _write_choice(tmp_path, {"device": "cpu", "compute_type": "int8",
                             "backend": "faster_whisper"})
    assert hw.device_choice_from_hardware_file() is None


def test_cpu_choice_saved_by_the_fixed_probe_is_honoured(monkeypatch, tmp_path):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    hw.save_hardware_choice(hw.Tier(
        slug="cpu_int8", label="CPU", device="cpu", compute_type="int8",
    ))
    assert hw.device_choice_from_hardware_file() == ("cpu", "int8")


def test_saved_cuda_compute_type_the_gpu_lacks_is_remapped(monkeypatch, tmp_path):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    _write_choice(tmp_path, {"device": "cuda", "compute_type": "int8_float16",
                             "backend": "faster_whisper", "probe_version": 2})
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=True, gpu_present=True, compute_types=("float16",),
    ))
    assert hw.device_choice_from_hardware_file() == ("cuda", "float16")


# ---------- the GPU warm-up pass ------------------------------------------------


class _WarmModel:
    def __init__(self, error: BaseException | None = None) -> None:
        self.error = error
        self.encoded: list[Any] = []

    def feature_extractor(self, audio):  # noqa: D401 - mimics faster-whisper
        import numpy as np
        return np.zeros((80, 101), dtype=np.float32)

    def encode(self, features):
        self.encoded.append(features)
        if self.error is not None:
            raise self.error


def test_warm_up_runs_one_padded_encoder_pass():
    pytest.importorskip("faster_whisper.audio")
    model = _WarmModel()
    hw.warm_up_cuda_model(model)
    assert len(model.encoded) == 1
    assert model.encoded[0].shape == (80, 3000)  # padded to Whisper's 30 s window


def test_warm_up_propagates_a_gpu_failure():
    pytest.importorskip("faster_whisper.audio")
    err = RuntimeError("CUDA failed with error no kernel image is available")
    with pytest.raises(RuntimeError, match="no kernel image"):
        hw.warm_up_cuda_model(_WarmModel(err))


def test_warm_up_skips_when_the_model_api_differs():
    """No feature_extractor / encode -> skip, never a false CPU downgrade."""
    hw.warm_up_cuda_model(object())


def test_warm_up_skips_an_input_shape_complaint():
    pytest.importorskip("faster_whisper.audio")
    hw.warm_up_cuda_model(_WarmModel(ValueError("Invalid input features shape")))
