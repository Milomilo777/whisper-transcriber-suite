"""Tests for the v0.8 hardware autodetect data layer.

The Tk dialog itself (``app.widgets.hardware_wizard.HardwareWizard``)
is harder to drive headless because Treeview interactions depend on
focus state; we cover the core probe + persistence logic here and
exercise the dialog construction in a single smoke test.
"""
from __future__ import annotations

import json
import os
import sys
import types
from pathlib import Path

import pytest

from core import hardware as hw


# ---------- Tier dataclass -----------------------------------------------------


def test_tier_dataclass_round_trips_via_asdict():
    t = hw.Tier(
        slug="cuda_float16",
        label="NVIDIA CUDA (float16) — RTX 4090",
        device="cuda",
        compute_type="float16",
        detail="RTX 4090",
    )
    d = hw.tier_to_dict(t)
    assert d["slug"] == "cuda_float16"
    assert d["device"] == "cuda"
    assert d["compute_type"] == "float16"
    assert d["backend"] == "faster_whisper"


# ---------- probe order --------------------------------------------------------


def test_probe_tiers_always_includes_cpu_fallback(monkeypatch):
    monkeypatch.setattr(hw, "_probe_cuda", lambda: [])
    monkeypatch.setattr(hw, "_probe_qnn_npu", lambda: [])
    monkeypatch.setattr(hw, "_probe_openvino", lambda: [])
    monkeypatch.setattr(hw, "_probe_directml", lambda: [])
    tiers = hw.probe_tiers()
    assert len(tiers) == 1
    assert tiers[-1].slug == "cpu_int8"
    assert tiers[-1].backend == "faster_whisper"


def test_probe_tiers_orders_cuda_above_cpu(monkeypatch):
    fake_cuda = hw.Tier(
        slug="cuda_float16", label="CUDA",
        device="cuda", compute_type="float16",
    )
    monkeypatch.setattr(hw, "_probe_cuda", lambda: [fake_cuda])
    monkeypatch.setattr(hw, "_probe_qnn_npu", lambda: [])
    monkeypatch.setattr(hw, "_probe_openvino", lambda: [])
    monkeypatch.setattr(hw, "_probe_directml", lambda: [])
    tiers = hw.probe_tiers()
    assert tiers[0].slug == "cuda_float16"
    assert tiers[-1].slug == "cpu_int8"


def test_first_supported_tier_skips_non_bundled(monkeypatch):
    fake_qnn = hw.Tier(
        slug="qnn_npu", label="QNN", device="cpu",
        compute_type="int8", backend="qnn_npu",
    )
    fake_cpu = hw.Tier(
        slug="cpu_int8", label="CPU", device="cpu",
        compute_type="int8",
    )
    chosen = hw.first_supported_tier([fake_qnn, fake_cpu])
    assert chosen.slug == "cpu_int8"


def test_first_supported_tier_picks_cuda_when_present():
    fake_cuda = hw.Tier(
        slug="cuda_float16", label="CUDA", device="cuda",
        compute_type="float16",
    )
    fake_cpu = hw.Tier(
        slug="cpu_int8", label="CPU", device="cpu",
        compute_type="int8",
    )
    chosen = hw.first_supported_tier([fake_cuda, fake_cpu])
    assert chosen.slug == "cuda_float16"


# ---------- CUDA probe ---------------------------------------------------------


def test_probe_cuda_returns_empty_when_no_device(monkeypatch):
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    assert hw._probe_cuda() == []


def test_probe_cuda_returns_both_compute_types_when_supported(monkeypatch):
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: 1  # type: ignore[attr-defined]
    fake_ct2.get_supported_compute_types = lambda _d: {  # type: ignore[attr-defined]
        "float16", "int8_float16",
    }
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    monkeypatch.setattr(hw, "_gpu_name", lambda: "RTX 9999")
    # R3: a device alone is no longer enough — the cuDNN/cuBLAS runtime must
    # also load. Stub the runtime gate True so this test still exercises the
    # compute-type ordering (the broken-runtime case is covered separately in
    # test_hardware_cuda_gate.py).
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: True)
    tiers = hw._probe_cuda()
    slugs = [t.slug for t in tiers]
    assert "cuda_float16" in slugs
    assert "cuda_int8_float16" in slugs
    # float16 must rank first (preferred compute type).
    assert slugs[0] == "cuda_float16"


def test_probe_cuda_handles_import_error_gracefully(monkeypatch):
    """When ctranslate2 isn't importable the probe returns [], not raise."""
    monkeypatch.setitem(sys.modules, "ctranslate2", None)
    assert hw._probe_cuda() == []


# ---------- persistence --------------------------------------------------------


def test_save_and_load_hardware_choice_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    tier = hw.Tier(
        slug="cuda_float16",
        label="NVIDIA CUDA (float16) — RTX 3060",
        device="cuda",
        compute_type="float16",
        detail="RTX 3060",
    )
    path = hw.save_hardware_choice(tier, benchmark_rtf=0.04)
    assert path.exists()
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tier"] == "cuda_float16"
    assert data["device"] == "cuda"
    assert data["compute_type"] == "float16"
    assert data["benchmark_rtf"] == 0.04
    assert data["version"] == hw.HARDWARE_FILE_VERSION

    loaded = hw.load_hardware_choice()
    assert loaded is not None
    assert loaded["tier"] == "cuda_float16"


def test_load_hardware_choice_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    assert hw.load_hardware_choice() is None


def test_load_hardware_choice_corrupt_file_renamed(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    path = tmp_path / hw.HARDWARE_FILE_NAME
    path.write_text("{not valid json", encoding="utf-8")
    assert hw.load_hardware_choice() is None
    assert not path.exists()
    assert (tmp_path / (hw.HARDWARE_FILE_NAME + ".corrupt")).exists()


# ---------- device_choice_from_hardware_file -----------------------------------


def test_device_choice_returns_pair_for_cpu_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    tier = hw.Tier(
        slug="cpu_int8", label="CPU", device="cpu", compute_type="int8",
    )
    hw.save_hardware_choice(tier)
    result = hw.device_choice_from_hardware_file()
    assert result == ("cpu", "int8")


def test_device_choice_rejects_non_bundled_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    tier = hw.Tier(
        slug="qnn_npu", label="QNN", device="cpu", compute_type="int8",
        backend="qnn_npu",
    )
    hw.save_hardware_choice(tier)
    # The detect_device path must not return a tier that needs a
    # backend the bundled engine can't drive.
    assert hw.device_choice_from_hardware_file() is None


def test_device_choice_revalidates_cuda_at_load(tmp_path, monkeypatch):
    """If the wizard saved CUDA but ctranslate2 no longer sees it
    (e.g. the user unplugged a Thunderbolt eGPU), the loader must
    return None so detect_device falls back to auto-probe instead
    of crashing the worker."""
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    tier = hw.Tier(
        slug="cuda_float16", label="CUDA",
        device="cuda", compute_type="float16",
    )
    hw.save_hardware_choice(tier)
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: 0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    assert hw.device_choice_from_hardware_file() is None


def test_device_choice_honours_cuda_when_still_present(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    tier = hw.Tier(
        slug="cuda_float16", label="CUDA",
        device="cuda", compute_type="float16",
    )
    hw.save_hardware_choice(tier)
    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: 1  # type: ignore[attr-defined]
    fake_ct2.get_supported_compute_types = lambda _d: {  # type: ignore[attr-defined]
        "float16", "int8_float16",
    }
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)
    # R3: the persisted CUDA choice is only honoured if the runtime libs also
    # load now; stub the gate True for this "still present" path.
    monkeypatch.setattr(hw, "_cuda_runtime_dlls_loadable", lambda: True)
    assert hw.device_choice_from_hardware_file() == ("cuda", "float16")


# ---------- detect_device integration ------------------------------------------


def test_detect_device_honours_hardware_file_when_device_is_auto(monkeypatch, tmp_path):
    """detect_device() with device='auto' must return the wizard's
    choice before falling back to its own probe."""
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    tier = hw.Tier(
        slug="cpu_int8", label="CPU", device="cpu", compute_type="int8",
    )
    hw.save_hardware_choice(tier)

    if "core.transcriber" not in sys.modules:
        fake_fw = types.ModuleType("faster_whisper")
        fake_fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules.setdefault("faster_whisper", fake_fw)
    import core.transcriber as t  # noqa: E402

    monkeypatch.setattr(t, "config", {"device": "auto", "compute_type": "int8"})
    # core.transcriber.detect_device does ``from . import hardware as _hw``
    # at call time — patching the shared core.hardware.user_data_dir
    # (which we already did above) is enough for it to read tmp_path.
    device, ct = t.detect_device()
    assert device == "cpu"
    assert ct == "int8"


# ---------- dialog smoke -------------------------------------------------------


def test_hardware_wizard_constructs_without_crashing(monkeypatch, tmp_path):
    tk = pytest.importorskip("tkinter")
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    # Force a single CPU tier so we don't depend on the host's actual
    # hardware in CI.
    monkeypatch.setattr(hw, "_probe_cuda", lambda: [])
    monkeypatch.setattr(hw, "_probe_qnn_npu", lambda: [])
    monkeypatch.setattr(hw, "_probe_openvino", lambda: [])
    monkeypatch.setattr(hw, "_probe_directml", lambda: [])
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=False, gpu_present=False, reason="No NVIDIA CUDA GPU was found.",
    ))

    from app.widgets.hardware_wizard import HardwareWizard

    root = tk.Tk()
    root.withdraw()
    try:
        wiz = HardwareWizard(root)
        wiz.withdraw()
        try:
            # The probe now runs OFF the Tk main thread to avoid freezing
            # the UI (BUG 3). Join the probe thread, then pump the Tk loop so
            # the main-thread poll (_poll_probe_result, scheduled via after())
            # applies the stashed result and populates the tree before we
            # assert.
            import time as _time

            probe = wiz._probe_thread
            if probe is not None:
                probe.join(timeout=10.0)
                assert not probe.is_alive(), "hardware probe did not finish"
            deadline = _time.time() + 5.0
            while _time.time() < deadline and not wiz.tree.get_children():
                wiz.update()
                _time.sleep(0.02)
            children = wiz.tree.get_children()
            assert len(children) == 1
            assert wiz._selected_idx == 0
            assert wiz._tiers[0].slug == "cpu_int8"
        finally:
            wiz._on_close()
    finally:
        root.destroy()


# ---------- cuDNN/cuBLAS dlopen probe is timeout-bounded -----------------------


def test_cuda_dll_probe_returns_false_on_wedged_loader(monkeypatch):
    """A wedged ctypes.CDLL must not freeze the probe.

    On a broken CUDA stack a single dlopen can block for many seconds inside
    the OS loader. _cuda_runtime_dlls_loadable runs the library loads in a
    helper thread with a bounded join; a timeout is treated as 'not loadable'
    (the safe CPU fallback) and the helper must return quickly.
    """
    import threading as _threading
    import time as _time

    started = _threading.Event()

    def _hang(_target):
        started.set()
        _time.sleep(30)  # simulate a wedged loader
        raise OSError("never reached")

    monkeypatch.setattr(hw, "_load_library", _hang)
    monkeypatch.setattr(hw, "_CUDA_DLL_PROBE_TIMEOUT_S", 0.2)

    t0 = _time.time()
    result = hw._cuda_runtime_dlls_loadable()
    elapsed = _time.time() - t0

    assert result is False
    # Must return on the timeout budget, not wait out the 30 s sleep.
    assert elapsed < 5.0
    assert started.is_set()


def test_cuda_dll_probe_true_when_libs_load(monkeypatch):
    """When every library the installed CTranslate2 needs loads, True."""

    def _loads(_target):
        return object()  # any non-raising load counts

    monkeypatch.setattr(hw, "_load_library", _loads)
    assert hw._cuda_runtime_dlls_loadable() is True


# ---------- benchmark clip temp-file cleanup -----------------------------------


def test_make_silent_clip_removes_temp_file_when_ffmpeg_fails(monkeypatch, tmp_path):
    """The benchmark's mkstemp'd WAV must not survive a failed ffmpeg run.

    ``_make_silent_clip`` creates the output file first, then runs ffmpeg.
    When ffmpeg could not run (missing bundled binary, bad args), the old
    code left the empty temp file behind on every benchmark attempt.
    """
    import subprocess as _sp

    from app.widgets import hardware_wizard as hwz

    target = tmp_path / "hw_bench_leftover.wav"
    fd = os.open(str(target), os.O_RDWR | os.O_CREAT)
    monkeypatch.setattr(
        hwz.tempfile, "mkstemp",
        lambda prefix="", suffix="": (fd, str(target)),
    )
    monkeypatch.setattr(hwz, "bundled_binary", lambda _name: "ffmpeg")

    def _boom(*args, **kwargs):
        raise _sp.CalledProcessError(1, "ffmpeg")

    monkeypatch.setattr(hwz.subprocess, "run", _boom)

    wiz = hwz.HardwareWizard.__new__(hwz.HardwareWizard)
    with pytest.raises(_sp.CalledProcessError):
        wiz._make_silent_clip(5)
    assert not target.exists()


# ---------- modal grab hand-back ------------------------------------------------


def test_close_restores_the_masters_modal_grab(monkeypatch, tmp_path):
    """Opening the wizard from a modal dialog (Advanced settings) replaces
    that dialog's Tk grab; closing the wizard must give it back."""
    tk = pytest.importorskip("tkinter")
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    monkeypatch.setattr(hw, "_probe_cuda", lambda: [])
    monkeypatch.setattr(hw, "_probe_qnn_npu", lambda: [])
    monkeypatch.setattr(hw, "_probe_openvino", lambda: [])
    monkeypatch.setattr(hw, "_probe_directml", lambda: [])
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(
        usable=False, gpu_present=False, reason="No NVIDIA CUDA GPU was found.",
    ))

    from app.widgets.hardware_wizard import HardwareWizard

    root = tk.Tk()
    root.withdraw()
    master = tk.Toplevel(root)
    master.withdraw()
    try:
        master.grab_set()
        assert root.grab_current() is master

        wiz = HardwareWizard(master)
        wiz.withdraw()
        assert root.grab_current() is wiz

        probe = wiz._probe_thread
        if probe is not None:
            probe.join(timeout=10.0)
        wiz._on_close()

        assert root.grab_current() is master
    finally:
        root.destroy()
