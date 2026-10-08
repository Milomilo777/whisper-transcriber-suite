"""Hardware detection and model recommendations: the review-fix findings.

Each test reproduces one finding with mocked GPUs / RAM / frozen builds (no real
hardware, no network) and fails on the code before its fix.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

import pytest

from core import hardware as hw
from core import offline


def _status(**kw: Any) -> hw.CudaStatus:
    base: dict[str, Any] = dict(
        usable=True, gpu_present=True, gpu_name="Test GPU", compute_capability="6.1",
        memory_mb=6144, device_count=1,
        compute_types=("float32", "int8", "int8_float32"),
    )
    base.update(kw)
    return hw.CudaStatus(**base)


_CPU_ONLY = hw.CudaStatus(usable=False, gpu_present=False)


# ---------------------------------------------------------------- S02-2 int8 tier


def test_pascal_gpu_without_float16_gets_a_cuda_int8_tier():
    """GTX 10-series: CTranslate2 reports int8 but no float16."""
    tiers = hw._probe_cuda(_status())
    assert [t.slug for t in tiers] == ["cuda_int8"]
    assert (tiers[0].device, tiers[0].compute_type) == ("cuda", "int8")
    full = hw.first_supported_tier(tiers + hw._probe_cpu())
    assert full.slug == "cuda_int8"


def test_int8_tier_goes_last_among_the_cuda_tiers():
    status = _status(compute_types=("float16", "int8", "int8_float16", "float32"))
    assert [t.slug for t in hw._probe_cuda(status)] == [
        "cuda_float16", "cuda_int8_float16", "cuda_int8",
    ]


def test_a_gpu_with_only_float32_offers_no_gpu_tier():
    assert hw._probe_cuda(_status(compute_types=("float32",))) == []


# ------------------------------------------------- S02-11 recommendations vs RAM


@pytest.mark.parametrize(
    "slug, ram, expected",
    [
        ("large-v3", 3.9, "small"),             # the 4 GB PC from the review (advice agrees)
        ("large-v3", 7.2, "large-v3"),          # an 8 GB laptop reports 7.0-7.4
        ("large-v3", 5.9, "large-v3-turbo"),
        ("large-v3-turbo", 3.9, "small"),
        ("medium", 4.9, "small"),               # under 5 GB: same line as the advisor
        ("medium", 5.0, "medium"),
        ("large-v3", 2.0, "small"),
        ("large-v3", 0.0, "large-v3"),          # RAM unknown: no cap
        ("small", 1.0, "small"),
        ("base", 1.0, "base"),
    ],
)
def test_model_is_capped_to_the_ram(slug, ram, expected):
    assert hw.fit_model_to_ram(slug, ram) == expected


def test_an_8gb_laptop_is_not_advised_like_a_weak_pc():
    picks = hw.recommend_models(_CPU_ONLY, ram_gb=7.2, cpu_cores=4)
    assert [p.slug for p in picks] == ["small", "large-v3-turbo"]


def test_a_4gb_pc_is_not_offered_a_big_model():
    picks = hw.recommend_models(_CPU_ONLY, ram_gb=3.9, cpu_cores=4)
    assert [p.slug for p in picks] == ["base", "small"]


def test_unreadable_ram_or_cores_are_not_treated_as_plenty():
    assert [p.slug for p in hw.recommend_models(_CPU_ONLY, ram_gb=0.0, cpu_cores=8)] == ["base", "small"]
    assert [p.slug for p in hw.recommend_models(_CPU_ONLY, ram_gb=16, cpu_cores=0)] == ["base", "small"]


def test_the_advisor_counts_physical_cores_not_threads(monkeypatch):
    """2 cores / 4 threads must not look like a 4-core machine."""
    monkeypatch.setattr(os, "cpu_count", lambda: 4)
    monkeypatch.setattr(hw, "physical_cpu_cores", lambda: 2)
    monkeypatch.setattr(hw, "system_ram_gb", lambda: 16.0)
    assert [p.slug for p in hw.recommend_models(_CPU_ONLY)] == ["base", "small"]


def test_a_forced_cpu_ignores_the_gpu():
    status = _status(memory_mb=24576, compute_types=("float16",))
    gpu_picks = [p.slug for p in hw.recommend_models(status, ram_gb=16, cpu_cores=8)]
    cpu_picks = [p.slug for p in hw.recommend_models(status, ram_gb=16, cpu_cores=8, force_cpu=True)]
    assert gpu_picks == ["large-v3-turbo", "large-v3"]
    assert cpu_picks == ["small", "large-v3-turbo"]


def test_a_forced_cpu_gets_the_cpu_time_estimate():
    status = _status(memory_mb=24576, compute_types=("float16",))
    on_gpu = hw.estimate_seconds_per_audio_minute("large-v3", status, physical_cores=4)
    on_cpu = hw.estimate_seconds_per_audio_minute(
        "large-v3", status, physical_cores=4, force_cpu=True,
    )
    assert on_gpu is not None and on_cpu is not None and on_cpu > 10 * on_gpu
    assert not hw.runs_on_gpu("large-v3", status, force_cpu=True)


def test_cpu_forced_by_config_or_by_the_saved_hardware_choice(monkeypatch):
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: None)
    assert hw.cpu_forced({"device": "cpu"})
    assert not hw.cpu_forced({"device": "auto"})
    assert not hw.cpu_forced({"device": "cuda"})
    assert not hw.cpu_forced({})
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: ("cpu", "int8"))
    assert hw.cpu_forced({"device": "auto"})
    assert not hw.cpu_forced({"device": "cuda"})  # an explicit setting wins over the file
    monkeypatch.setattr(hw, "device_choice_from_hardware_file", lambda: ("cuda", "float16"))
    assert not hw.cpu_forced({"device": "auto"})


def test_a_saved_hardware_file_cannot_crash_the_cpu_check(monkeypatch):
    def boom() -> None:
        raise OSError("disk gone")

    monkeypatch.setattr(hw, "device_choice_from_hardware_file", boom)
    assert hw.cpu_forced({"device": "auto"}) is False


def test_advisor_summary_does_not_claim_a_missing_nvidia_gpu_on_a_mac():
    from app.dialogs.model_advisor import advisor_summary

    text = advisor_summary(_CPU_ONLY, cores=8, ram_gb=16, platform="darwin")
    assert "NVIDIA" not in text
    assert "8" in text and "16" in text
    assert "No usable NVIDIA GPU" in advisor_summary(_CPU_ONLY, cores=8, ram_gb=16, platform="win32")


def test_advisor_summary_says_when_the_cpu_is_forced():
    from app.dialogs.model_advisor import advisor_summary

    status = _status(memory_mb=8192, compute_types=("float16",))
    text = advisor_summary(status, cores=8, ram_gb=16, platform="win32", force_cpu=True)
    assert "models run on the GPU" not in text
    assert "CPU" in text


# ------------------------------------------------------------ H3 cp1252 output


def test_diagnostics_print_survives_a_cp1252_stdout(monkeypatch):
    persian = "C:\\\u067e\u0648\u0634\u0647\\python.exe"  # a Persian folder name
    monkeypatch.setattr(hw, "diagnostics_report", lambda: f"Python: {persian}")
    raw = io.BytesIO()
    fake = io.TextIOWrapper(raw, encoding="cp1252", errors="strict", write_through=True)
    monkeypatch.setattr(sys, "stdout", fake)
    hw.main()
    fake.flush()
    assert persian.encode("utf-8") in raw.getvalue()


# ------------------------------------------------------------- hardware wizard


def _wizard_fake(**kw: Any) -> types.SimpleNamespace:
    closed: list[bool] = []
    base: dict[str, Any] = dict(
        _tiers=[], _selected_idx=0, _user_picked=False, _cuda_status=None,
        app=None, _closed=closed,
    )
    base.update(kw)
    fake = types.SimpleNamespace(**base)
    fake._on_close = lambda: closed.append(True)
    fake._restart_idle_engine = lambda: None
    return fake


@pytest.fixture
def hw_file(tmp_path, monkeypatch):
    monkeypatch.setattr(hw, "user_data_dir", lambda: tmp_path)
    return hw.hardware_json_path()


def test_the_wizard_has_no_misleading_benchmark():
    from app.widgets import hardware_wizard as hwz

    assert not hasattr(hwz.HardwareWizard, "_run_benchmark")
    assert not hasattr(hwz.HardwareWizard, "_benchmark_worker")


def test_saving_does_not_store_a_benchmark_speed(hw_file):
    from app.widgets.hardware_wizard import HardwareWizard

    tier = hw._probe_cpu()[0]
    fake = _wizard_fake(_tiers=[tier], _cuda_status=_CPU_ONLY)
    HardwareWizard._save_and_close(fake)  # type: ignore[arg-type]
    import json

    assert json.loads(hw_file.read_text(encoding="utf-8"))["benchmark_rtf"] is None


def test_a_tier_of_an_unbundled_backend_cannot_be_saved(hw_file, monkeypatch):
    from app.widgets import hardware_wizard as hwz

    shown: list[str] = []
    monkeypatch.setattr(hwz.messagebox, "showinfo", lambda title, *_a, **_k: shown.append(title))
    tier = hw.Tier(
        slug="directml", label="DirectML", device="cpu", compute_type="int8", backend="directml",
    )
    fake = _wizard_fake(_tiers=[tier], _user_picked=True)
    hwz.HardwareWizard._save_and_close(fake)  # type: ignore[arg-type]
    assert not hw_file.exists()
    assert shown and fake._closed == []  # the window stays open


def test_the_save_button_follows_the_selected_tier():
    from app.widgets.hardware_wizard import HardwareWizard

    states: list[list[str]] = []
    fake = types.SimpleNamespace(
        _busy=False, save_btn=types.SimpleNamespace(state=lambda s: states.append(list(s))),
        _tiers=[hw._probe_cpu()[0], hw.Tier("directml", "D", "cpu", "int8", backend="directml")],
        _selected_idx=1,
    )
    HardwareWizard._sync_save_button(fake)  # type: ignore[arg-type]
    fake._selected_idx = 0
    HardwareWizard._sync_save_button(fake)  # type: ignore[arg-type]
    assert states == [["disabled"], ["!disabled"]]


def test_the_automatic_cpu_pick_is_not_saved_over_an_unusable_gpu(hw_file):
    """Apply on the untouched list wrote device=cpu for good, so a later
    driver fix never reached the automatic cuda pick."""
    from app.widgets.hardware_wizard import HardwareWizard

    tier = hw._probe_cpu()[0]
    status = hw.CudaStatus(usable=False, gpu_present=True, reason="cuBLAS missing")
    fake = _wizard_fake(_tiers=[tier], _cuda_status=status)
    HardwareWizard._save_and_close(fake)  # type: ignore[arg-type]
    assert not hw_file.exists()
    assert fake._closed == [True]


def test_a_deliberate_cpu_choice_is_still_saved(hw_file):
    from app.widgets.hardware_wizard import HardwareWizard

    tier = hw._probe_cpu()[0]
    status = hw.CudaStatus(usable=False, gpu_present=True)
    fake = _wizard_fake(_tiers=[tier], _cuda_status=status, _user_picked=True)
    HardwareWizard._save_and_close(fake)  # type: ignore[arg-type]
    assert hw_file.exists()


def test_the_cpu_pick_is_saved_on_a_pc_without_an_nvidia_gpu(hw_file):
    from app.widgets.hardware_wizard import HardwareWizard

    fake = _wizard_fake(_tiers=[hw._probe_cpu()[0]], _cuda_status=_CPU_ONLY)
    HardwareWizard._save_and_close(fake)  # type: ignore[arg-type]
    assert hw_file.exists()


def test_the_gpu_download_question_is_not_asked_while_offline(monkeypatch):
    """The 550 MB question came before the Work offline check."""
    from app.widgets import hardware_wizard as hwz

    asked: list[str] = []
    monkeypatch.setattr(hwz.messagebox, "askyesno", lambda *a, **k: asked.append("ask") or True)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: True)
    statuses: list[str] = []
    fake = types.SimpleNamespace(
        _cuda_status=_status(can_install_runtime=True, usable=False), _busy=False,
        status_var=types.SimpleNamespace(set=statuses.append),
    )
    hwz.HardwareWizard._install_gpu_support(fake)  # type: ignore[arg-type]
    assert asked == []
    assert statuses and "Offline mode" in statuses[0]


# ----------------------------------------------- S02-4 frozen macOS app and engines


def test_frozen_nvidia_backend_does_not_promise_an_install(monkeypatch):
    from core.backends import nvidia_asr
    from core.optional_deps import FROZEN_INSTALL_MESSAGE

    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(nvidia_asr, "_deps_available", lambda: False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    messages: list[str] = []
    backend = nvidia_asr.NvidiaAsrBackend(config={})
    assert backend.load(status_cb=messages.append) is False
    assert backend.get_error() == FROZEN_INSTALL_MESSAGE
    joined = " ".join(messages)
    assert "Installing" not in joined and "pip install" not in joined


def test_frozen_picker_does_not_say_install_on_first_use(monkeypatch):
    from core.backends import availability
    from core.optional_deps import FROZEN_INSTALL_MESSAGE

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    real = __import__("importlib.util").util.find_spec
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name, *a: None if name == "transformers" else real(name, *a),
    )
    st = availability._nvidia_asr_status({})
    assert not st.ready and st.blocked
    assert "first use" not in st.detail
    assert st.detail == FROZEN_INSTALL_MESSAGE


def test_light_status_does_not_call_nvidia_asr_ready(monkeypatch):
    from core.backends import availability

    real = __import__("importlib.util").util.find_spec
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name, *a: None if name == "transformers" else real(name, *a),
    )
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    st = availability.engine_status("nvidia_asr", {}, deep=False)
    assert not st.ready
    assert "first use" in st.detail


def test_light_status_keeps_nvidia_asr_ready_when_the_package_is_present(monkeypatch):
    from core.backends import availability

    real = __import__("importlib.util").util.find_spec
    fake_spec = object()
    monkeypatch.setattr(
        "importlib.util.find_spec", lambda name, *a: fake_spec if name == "transformers" else real(name, *a),
    )
    assert availability.engine_status("nvidia_asr", {}, deep=False).ready


# ------------------------------------------------ H2 device index, H8 cancel


@pytest.mark.parametrize(
    "device, index", [("cuda", 0), ("cuda:1", 1), ("CUDA:2", 2), ("cuda:x", 0), ("cpu", -1)],
)
def test_nvidia_device_index(device, index):
    from core.backends import nvidia_asr

    assert nvidia_asr.device_index(device) == index


def test_cancel_during_pause_does_not_decode_another_window(monkeypatch):
    from core.backends import nvidia_asr

    backend = nvidia_asr.NvidiaAsrBackend(config={})
    backend._ready = True
    backend._pipe = object()
    decoded: list[float] = []
    monkeypatch.setattr(
        nvidia_asr, "_decode_window", lambda *a: decoded.append(a[1]) or (_ for _ in ()).throw(AssertionError),
    )
    state = {"cancel": False}

    def paused() -> bool:
        state["cancel"] = True  # the user cancels while the job is paused
        return True

    segments, _info = backend.transcribe_to_segments(
        "x.wav", cancelled=lambda: state["cancel"], paused=paused, duration=120.0,
    )
    assert decoded == []
    assert segments == []


# ----------------------------------------------------- S02-3 optional-deps merge


@pytest.mark.parametrize("real_wheels", [False, True], ids=["namespace", "empty-init"])
def test_installing_cuda_runtime_keeps_nvidia_cudnn_from_an_earlier_install(
    monkeypatch, tmp_path, real_wheels,
):
    """``real_wheels``: the NVIDIA wheels ship empty ``__init__.py`` files."""
    from core import optional_deps as od

    extras = tmp_path / "pylibs"
    cudnn = extras / "nvidia" / "cudnn" / "lib"
    cudnn.mkdir(parents=True)
    (cudnn / "libcudnn.so.9").write_bytes(b"x")  # left by an earlier torch install
    old_cublas = extras / "nvidia" / "cublas" / "lib"
    old_cublas.mkdir(parents=True)
    (old_cublas / "old.so").write_bytes(b"old")
    if real_wheels:
        (extras / "nvidia" / "__init__.py").write_bytes(b"")
        (extras / "nvidia" / "cublas" / "__init__.py").write_bytes(b"")
    monkeypatch.setattr(od, "extras_dir", lambda: str(extras))
    monkeypatch.setattr(od, "can_install", lambda: True)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(sys, "path", list(sys.path))

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, **kw):
            staging = Path(cmd[cmd.index("--target") + 1])
            (staging / "nvidia" / "cublas" / "lib").mkdir(parents=True)
            (staging / "nvidia" / "cublas" / "lib" / "libcublas.so.12").write_bytes(b"y")
            if real_wheels:
                (staging / "nvidia" / "__init__.py").write_bytes(b"")
                (staging / "nvidia" / "cublas" / "__init__.py").write_bytes(b"")
            self.stdout = io.StringIO("")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    od.install("cuda_runtime", log_cb=lambda _m: None, force=True)
    assert (cudnn / "libcudnn.so.9").exists(), "the earlier nvidia/cudnn was deleted"
    assert (extras / "nvidia" / "cublas" / "lib" / "libcublas.so.12").exists()
    if real_wheels:  # a real package folder below the shared one is replaced as a whole
        assert not (old_cublas / "old.so").exists()
    leftovers = [p.name for p in (extras / "nvidia").iterdir() if p.name.startswith(".")]
    assert leftovers == []


def test_a_failed_nested_merge_restores_what_it_displaced(monkeypatch, tmp_path):
    from core import optional_deps as od

    extras = tmp_path / "pylibs"
    keep = extras / "nvidia" / "cudnn" / "lib"
    keep.mkdir(parents=True)
    (keep / "libcudnn.so.9").write_bytes(b"x")
    monkeypatch.setattr(od, "extras_dir", lambda: str(extras))
    monkeypatch.setattr(od, "can_install", lambda: True)
    monkeypatch.setattr(offline, "is_offline", lambda *a, **k: False)
    monkeypatch.setattr(sys, "path", list(sys.path))

    class FakeProc:
        returncode = 0

        def __init__(self, cmd, **kw):
            staging = Path(cmd[cmd.index("--target") + 1])
            (staging / "nvidia" / "cublas" / "lib").mkdir(parents=True)
            (staging / "nvidia" / "cublas" / "lib" / "libcublas.so.12").write_bytes(b"y")
            self.stdout = io.StringIO("")

        def wait(self, timeout=None):
            return 0

    monkeypatch.setattr(subprocess, "Popen", FakeProc)
    real_copytree = od.shutil.copytree

    def failing_copytree(src, dst, *a, **k):
        if "cublas" in str(src):
            raise PermissionError("locked")
        return real_copytree(src, dst, *a, **k)

    monkeypatch.setattr(od.shutil, "copytree", failing_copytree)
    assert od.install("cuda_runtime", log_cb=lambda _m: None, force=True) is False
    assert (keep / "libcudnn.so.9").exists()
    assert not (extras / "nvidia" / "cublas").exists()


# ------------------------------------------------------------ reviewer findings


def test_a_package_with_an_empty_init_is_still_replaced_as_a_whole(tmp_path):
    """typing_inspection-style packages have an empty __init__.py plus modules;
    merging them file by file would keep removed modules of the old version."""
    from core import optional_deps as od

    staging, final = tmp_path / "stage", tmp_path / "final"
    for root, extra in ((staging, "new.py"), (final, "old_removed.py")):
        (root / "pkg").mkdir(parents=True)
        (root / "pkg" / "__init__.py").write_bytes(b"")
        (root / "pkg" / extra).write_bytes(b"x")
    units = od._merge_units(str(staging), str(final))
    assert units == [(str(staging / "pkg"), str(final / "pkg"))]


def test_quick_start_caps_the_model_before_the_hardware_check_finishes(monkeypatch):
    from app.dialogs import quick_start as qs

    monkeypatch.setattr(hw, "system_ram_gb", lambda: 3.9)
    choice = qs.QuickStartChoice("fa", "best", "x", ram_gb=hw.system_ram_gb())
    assert choice.model_slug == "small"


def test_a_reprobe_forgets_the_earlier_click():
    tk = pytest.importorskip("tkinter")
    from app.widgets.hardware_wizard import HardwareWizard

    root = tk.Tk()
    root.withdraw()
    try:
        wiz = HardwareWizard(root)
        wiz.withdraw()
        if wiz._probe_thread is not None:
            wiz._probe_thread.join(timeout=10.0)
        wiz._user_picked = True
        status = hw.CudaStatus(usable=False, gpu_present=True)
        wiz._reprobe_done(wiz._probe_seq, hw._probe_cpu(), status)
        assert wiz._user_picked is False
        wiz._on_close()
    finally:
        root.destroy()
