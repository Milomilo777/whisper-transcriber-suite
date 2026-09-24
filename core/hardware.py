"""Hardware autodetect — probe, persist, and load the chosen tier.

This module is the data-access layer the Hardware Wizard UI sits on
top of. It MUST stay Tk-free so ``core.transcriber.detect_device``
can call :func:`load_hardware_choice` without dragging tkinter into
the worker subprocess.

Tier probe order (best → worst):

  CUDA float16 → CUDA int8_float16 → QNN NPU (Snapdragon) →
  Intel NPU (OpenVINO) → OpenVINO GPU → DirectML →
  faster-whisper CPU int8

For each detected tier the wizard records:

  * ``slug``        — stable identifier (``cuda_float16``)
  * ``label``       — human description for the UI
  * ``device``      — what to pass to ``WhisperModel(device=...)``
  * ``compute_type``— matching ``compute_type`` argument
  * ``backend``     — ``faster_whisper`` for the bundled engine; one
    of the other tier slugs when the user has to switch backends to
    actually use it (we still surface the tier so they know it's
    possible)
  * ``detail``      — free-form text (GPU model, OpenVINO device id)

The chosen tier is persisted as ``hardware.json`` next to the rest
of the user data so it survives reinstall + roams with a profile.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import sys
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Callable, TypeVar

from ._gc_import_guard import gc_disabled_import
from .config import user_data_dir


logger = logging.getLogger(__name__)

_T = TypeVar("_T")


HARDWARE_FILE_NAME = "hardware.json"
HARDWARE_FILE_VERSION = 1

# Bumped whenever the probe that writes hardware.json gains the ability to
# see hardware it could not see before. Probe version 1 (everything up to and
# including v1.9.1) could NEVER report a CUDA GPU -- it called a CTranslate2
# function that does not exist (GitHub issue #7) -- so a CPU choice saved by
# it says nothing about the user's real preference and is re-probed instead of
# honoured. See device_choice_from_hardware_file().
HARDWARE_PROBE_VERSION = 2


@dataclass(frozen=True)
class Tier:
    slug: str
    label: str
    device: str
    compute_type: str
    backend: str = "faster_whisper"
    detail: str = ""


def hardware_json_path() -> Path:
    return user_data_dir() / HARDWARE_FILE_NAME


# ---------------------------------------------------------------- probes


# ---- CTranslate2's view of the GPU ---------------------------------------------
#
# GitHub issue #7 post-mortem: up to v1.9.1 every CUDA check in this module
# called ``ctranslate2.contains_cuda_device()``. No released CTranslate2 has
# that function -- the real API is ``get_cuda_device_count()`` (checked against
# the 3.24 and 4.4 - 4.8.2 wheels). The AttributeError was swallowed by the
# surrounding ``except Exception``, so CUDA was reported absent on EVERY
# machine, silently. The unit tests could not notice because they replaced
# ctranslate2 with a fake module that did define the missing function;
# tests/core/test_hardware_ct2_contract.py now checks the CTranslate2 API this
# module uses against the real installed package.


def _ct2_cuda_device_count(ct2: Any) -> int:
    """Number of CUDA devices CTranslate2 can use; 0 on any failure.

    Calls the real ``get_cuda_device_count()``. The old
    ``contains_cuda_device()`` name is only a getattr-guarded fallback for a
    build that might expose it; nothing here can raise AttributeError.
    """
    fn: Any = getattr(ct2, "get_cuda_device_count", None)
    if callable(fn):
        try:
            count: Any = fn()
            return max(0, int(count))
        except Exception:  # noqa: BLE001
            return 0
    legacy: Any = getattr(ct2, "contains_cuda_device", None)
    if callable(legacy):
        try:
            return 1 if legacy() else 0
        except Exception:  # noqa: BLE001
            return 0
    return 0


def _ct2_version(ct2: Any) -> tuple[int, ...]:
    """``ctranslate2.__version__`` as an int tuple, e.g. (4, 8, 2); () if unknown."""
    parts: list[int] = []
    for piece in str(getattr(ct2, "__version__", "") or "").split(".")[:3]:
        m = re.match(r"\d+", piece)
        if not m:
            break
        parts.append(int(m.group(0)))
    return tuple(parts)


def _run_with_timeout(fn: Callable[[], _T], timeout: float, default: _T) -> _T:
    """Run ``fn`` on a daemon thread; ``default`` if it raises or overruns.

    Loading a GPU library or initialising the NVIDIA driver can block for a
    long time inside the OS loader on a broken install. The caller must never
    hang on that (the Hardware wizard and the worker's device pick both run
    these probes), so an overrunning call is abandoned and reads as "not
    available".
    """
    box: dict[str, Any] = {}

    def _target() -> None:
        try:
            box["value"] = fn()
        except Exception:  # noqa: BLE001
            logger.debug("CUDA probe helper raised", exc_info=True)

    t = threading.Thread(target=_target, name="cuda-probe", daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive() or "value" not in box:
        return default
    return box["value"]


# ---- CUDA runtime libraries --------------------------------------------------------
#
# ``get_cuda_device_count()`` only proves a driver + GPU exist. The CUDA math
# libraries CTranslate2 needs are loaded lazily, by file name, at the first GPU
# forward pass. What the wheels actually load (read from their binaries):
#
#   * cuBLAS for their CUDA major version: 12 for CTranslate2 4.x, 11 for 3.x.
#   * cuDNN only BEFORE 4.6.3 (cuDNN 9 from 4.5.0, cuDNN 8 before that). 4.6.3
#     and later have no cuDNN dependency at all -- the cudnn64_9.dll inside the
#     Windows wheel is unused -- so the old "needs cuDNN AND cuBLAS" gate
#     refused setups that would have worked.
#
# The NVIDIA driver ships none of these. They come from the CUDA Toolkit, from
# NVIDIA's pip wheels (``nvidia-cublas-cu12`` puts cublas64_12.dll under
# site-packages/nvidia/cublas/bin), or inside a CUDA build of PyTorch
# (torch/lib). None of those folders is on a plain Python process's DLL search
# path. On Windows, Python's default ``ctypes.CDLL(name)`` flags do not search
# PATH either, while CTranslate2's own LoadLibrary does, so the old probe could
# disagree with the engine both ways. ``prepare_cuda_runtime()`` checks all of
# those places, loads what it finds by full path (a later by-name load inside
# CTranslate2 then resolves to that already-loaded module, on Windows and on
# glibc alike) and adds the folder to the DLL search path for anything loaded
# after that.

# pip package that provides cuBLAS for the CUDA major CTranslate2 4.x uses. The
# Hardware wizard's "Install GPU support" button installs it through
# core.optional_deps (feature "cuda_runtime"). 12.8+ is the first cuBLAS with
# native RTX 50-series / Blackwell (sm_120) kernels.
CUDA_RUNTIME_PIP_PACKAGE = "nvidia-cublas-cu12"

_NVIDIA_WHEEL_PACKAGES = ("cublas", "cudnn", "cuda_runtime", "cuda_nvrtc")

# Worst-case wall-clock budget for loading the CUDA runtime libraries. Usually
# instant, but cuBLAS is two large DLLs (~100 MB + ~670 MB for CUDA 12) that
# antivirus scans on first load, and on a broken CUDA install a single load can
# block inside the OS loader. The load runs in a helper thread; a timeout reads
# as "not loadable" (the safe CPU fallback) and never freezes the caller.
_CUDA_DLL_PROBE_TIMEOUT_S = 15.0
_CUDA_DRIVER_PROBE_TIMEOUT_S = 10.0

# Where each successfully loaded CUDA library came from (file name -> path or
# "system search path"), for diagnostics. Handles are kept referenced so the
# libraries stay loaded for CTranslate2.
_LOADED_CUDA_LIBS: dict[str, str] = {}
_LOADED_HANDLES: list[Any] = []
_DLL_DIR_HANDLES: list[Any] = []
_registered_dll_dirs: set[str] = set()


def _required_cuda_libs(ct2_version: tuple[int, ...]) -> dict[str, tuple[str, ...]]:
    """Library family -> candidate file names this CTranslate2 build loads.

    An unknown version is treated as current (CUDA 12 cuBLAS only).
    """
    win = sys.platform == "win32"
    known = bool(ct2_version)
    cuda_major = 11 if known and ct2_version < (4,) else 12
    libs: dict[str, tuple[str, ...]] = {
        "cuBLAS": (
            (f"cublas64_{cuda_major}.dll",) if win
            else (f"libcublas.so.{cuda_major}",)
        ),
    }
    if known and ct2_version < (4, 6, 3):
        if ct2_version >= (4, 5):
            libs["cuDNN"] = ("cudnn_ops64_9.dll",) if win else ("libcudnn_ops.so.9",)
        else:
            libs["cuDNN"] = (
                ("cudnn_ops_infer64_8.dll",) if win
                else ("libcudnn_ops_infer.so.8", "libcudnn.so.8")
            )
    return libs


def _pip_packages_for(families: list[str], ct2_version: tuple[int, ...]) -> list[str]:
    """NVIDIA pip wheels that provide the given library families."""
    suffix = "cu11" if ct2_version and ct2_version < (4,) else "cu12"
    names = {"cuBLAS": f"nvidia-cublas-{suffix}", "cuDNN": f"nvidia-cudnn-{suffix}"}
    return [names[f] for f in families if f in names]


def _python_roots() -> list[str]:
    """sys.path entries plus the on-demand extras dir, de-duplicated.

    The extras dir is where the wizard's "Install GPU support" puts
    nvidia-cublas-cu12; it is listed first so a runtime installed by the app
    wins over an older one that happens to sit elsewhere.
    """
    roots: list[str] = []
    try:
        from .optional_deps import extras_dir
        roots.append(extras_dir())
    except Exception:  # noqa: BLE001
        pass
    roots.extend(p for p in sys.path if isinstance(p, str) and p)
    seen: set[str] = set()
    out: list[str] = []
    for r in roots:
        key = os.path.normcase(os.path.abspath(r))
        if key not in seen:
            seen.add(key)
            out.append(r)
    return out


def _cuda_library_dir_groups() -> tuple[list[str], list[str]]:
    """(preferred, fallback) existing folders that may hold CUDA libraries.

    Preferred: NVIDIA's pip wheels (what the app itself installs; searched
    before the system search path). Fallback, after it: CUDA Toolkit installs,
    the standalone cuDNN installer, and a CUDA build of PyTorch.
    """
    win = sys.platform == "win32"
    sub = "bin" if win else "lib"
    roots = _python_roots()
    preferred = [
        os.path.join(root, "nvidia", pkg, sub)
        for root in roots for pkg in _NVIDIA_WHEEL_PACKAGES
    ]
    fallback: list[str] = []
    # CUDA_PATH_V12_8 before CUDA_PATH_V12_4 before plain CUDA_PATH.
    for key in sorted(os.environ, reverse=True):
        up = key.upper()
        if up == "CUDA_PATH" or up.startswith("CUDA_PATH_V"):
            base = os.environ.get(key) or ""
            if base:
                fallback += [
                    os.path.join(base, "bin"),
                    os.path.join(base, "bin", "x64"),
                    os.path.join(base, "lib64"),
                ]
    if win:
        program_files = os.environ.get("ProgramFiles") or r"C:\Program Files"
        # Standalone cuDNN installer layout: NVIDIA\CUDNN\v9.x\bin\12.x
        fallback += sorted(
            glob.glob(os.path.join(program_files, "NVIDIA", "CUDNN", "v*", "bin", "*")),
            reverse=True,
        )
    else:
        fallback += ["/usr/local/cuda/lib64", "/usr/local/cuda/targets/x86_64-linux/lib"]
    fallback += [os.path.join(root, "torch", "lib") for root in roots]

    seen: set[str] = set()

    def _existing(dirs: list[str]) -> list[str]:
        out: list[str] = []
        for d in dirs:
            key = os.path.normcase(os.path.abspath(d))
            if key in seen:
                continue
            seen.add(key)
            if os.path.isdir(d):
                out.append(d)
        return out

    return _existing(preferred), _existing(fallback)


def cuda_library_dirs() -> list[str]:
    """Every existing folder searched for CUDA runtime libraries, best first."""
    preferred, fallback = _cuda_library_dir_groups()
    return preferred + fallback


def _load_library(target: str) -> Any:
    """Load a shared library the way CTranslate2 will look for it.

    A bare name on Windows uses the standard search order (``winmode=0``:
    application folder, System32, PATH, ...), which is what CTranslate2's own
    LoadLibrary uses; Python's default ``ctypes.CDLL`` flags skip PATH. A full
    path loads that exact file, and its own folder is searched for its
    dependencies (cublasLt64_12.dll next to cublas64_12.dll).
    """
    import ctypes
    if sys.platform == "win32" and not os.path.isabs(target):
        return ctypes.CDLL(target, winmode=0)
    return ctypes.CDLL(target)


def _module_path(handle: Any) -> str:
    """File a loaded library came from (Windows only; "" when unknown)."""
    if sys.platform == "win32":
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(1024)
            n = ctypes.windll.kernel32.GetModuleFileNameW(
                ctypes.c_void_p(handle._handle), buf, 1024,
            )
            return buf.value if n else ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _add_to_dll_search_path(folder: str) -> None:
    """Windows: make ``folder`` visible to later by-name DLL loads.

    ``os.add_dll_directory`` covers loads made through Python; PATH covers the
    native LoadLibrary calls inside CTranslate2 (and cuDNN's sub-libraries) and
    is inherited by the transcription worker processes started afterwards.
    """
    if sys.platform != "win32":
        return
    key = os.path.normcase(os.path.abspath(folder))
    if key in _registered_dll_dirs:
        return
    _registered_dll_dirs.add(key)
    add_dir = getattr(os, "add_dll_directory", None)
    if add_dir is not None:
        try:
            _DLL_DIR_HANDLES.append(add_dir(folder))
        except OSError:
            pass
    path = os.environ.get("PATH", "")
    entries = {os.path.normcase(os.path.abspath(p)) for p in path.split(os.pathsep) if p}
    if key not in entries:
        os.environ["PATH"] = folder + (os.pathsep + path if path else "")


def _load_first(
    names: tuple[str, ...],
    preferred_dirs: list[str],
    fallback_dirs: list[str],
    errors: list[str],
) -> str | None:
    """Load the first loadable candidate; return where it came from, or None.

    Order: preferred folders by full path, then the system search path by
    name, then fallback folders by full path. A file that exists but fails to
    load (a missing dependency, a wrong-architecture DLL) is recorded in
    ``errors`` for the diagnostics report.
    """
    candidates: list[str] = []
    for d in preferred_dirs:
        candidates += [os.path.join(d, n) for n in names if os.path.isfile(os.path.join(d, n))]
    candidates += list(names)
    for d in fallback_dirs:
        candidates += [os.path.join(d, n) for n in names if os.path.isfile(os.path.join(d, n))]
    for target in candidates:
        try:
            handle = _load_library(target)
        except Exception as e:  # noqa: BLE001
            if os.path.isabs(target):
                errors.append(f"{target}: {e}")
            continue
        if os.path.isabs(target):
            where = target
            _add_to_dll_search_path(os.path.dirname(target))
        else:
            where = _module_path(handle) or f"{target} (system search path)"
        _LOADED_HANDLES.append(handle)
        _LOADED_CUDA_LIBS[os.path.basename(target)] = where
        return where
    return None


def _resolve_cuda_runtime_libs(ct2_version: tuple[int, ...]) -> dict[str, str | None]:
    """Library family -> where it loaded from (None = not found). May block."""
    preferred, fallback = _cuda_library_dir_groups()
    result: dict[str, str | None] = {}
    for family, names in _required_cuda_libs(ct2_version).items():
        errors: list[str] = []
        result[family] = _load_first(names, preferred, fallback, errors)
        if result[family] is None and errors:
            logger.info("%s found but failed to load: %s", family, "; ".join(errors))
    return result


def _installed_ct2_version() -> tuple[int, ...]:
    try:
        import ctranslate2  # type: ignore[import-not-found]
        return _ct2_version(ctranslate2)
    except Exception:  # noqa: BLE001
        return ()


def _cuda_runtime_report(
    ct2_version: tuple[int, ...] | None = None,
) -> dict[str, str | None] | None:
    """Timeout-bounded :func:`_resolve_cuda_runtime_libs`; None if it stalled."""
    version = _installed_ct2_version() if ct2_version is None else ct2_version
    return _run_with_timeout(
        lambda: _resolve_cuda_runtime_libs(version), _CUDA_DLL_PROBE_TIMEOUT_S, None,
    )


def _cuda_runtime_dlls_loadable() -> bool:
    """True when every CUDA runtime library the installed CTranslate2 needs loads.

    Also *prepares* them: what it finds outside the default search path is
    loaded and its folder registered, so CTranslate2's own lazy load later
    succeeds in this process. Never raises; a stalled loader reads as False.
    """
    report = _cuda_runtime_report()
    return bool(report) and all(report.values())


def prepare_cuda_runtime() -> bool:
    """Locate + load the CUDA runtime libraries before a CUDA model load.

    Called by the worker right before ``WhisperModel(device="cuda")`` so the
    libraries found in NVIDIA's pip wheels / a CUDA Toolkit / torch are in
    place when CTranslate2 goes looking for them by name.
    """
    return _cuda_runtime_dlls_loadable()


# ---- what the NVIDIA driver itself reports -------------------------------------


def _cuda_driver_info() -> dict[str, Any]:
    """GPU list from the CUDA driver API, independent of CTranslate2 and torch.

    nvcuda.dll / libcuda.so.1 ship with the NVIDIA driver itself, so this
    works on a machine with no CUDA Toolkit. Returns
    ``{"driver_version": 13040, "gpus": [{"name", "cc": (12, 0), "memory_mb"}]}``
    or ``{}`` when there is no usable NVIDIA driver. May block on a broken
    driver: call it through ``_run_with_timeout``.
    """
    if sys.platform == "win32":
        names: tuple[str, ...] = ("nvcuda.dll",)
    elif sys.platform.startswith("linux"):
        names = ("libcuda.so.1", "libcuda.so")
    else:
        return {}
    import ctypes
    lib: Any = None
    for n in names:
        try:
            lib = ctypes.CDLL(n)
            break
        except OSError:
            continue
    if lib is None or lib.cuInit(0) != 0:
        return {}
    version = ctypes.c_int(0)
    info: dict[str, Any] = {"driver_version": 0, "gpus": []}
    if lib.cuDriverGetVersion(ctypes.byref(version)) == 0:
        info["driver_version"] = version.value
    count = ctypes.c_int(0)
    if lib.cuDeviceGetCount(ctypes.byref(count)) != 0:
        return info
    total_mem = getattr(lib, "cuDeviceTotalMem_v2", None) or getattr(lib, "cuDeviceTotalMem", None)
    for i in range(count.value):
        dev = ctypes.c_int(0)
        if lib.cuDeviceGet(ctypes.byref(dev), i) != 0:
            continue
        name = ctypes.create_string_buffer(256)
        lib.cuDeviceGetName(name, 256, dev)
        major, minor = ctypes.c_int(0), ctypes.c_int(0)
        # 75 / 76 = CU_DEVICE_ATTRIBUTE_COMPUTE_CAPABILITY_MAJOR / _MINOR
        lib.cuDeviceGetAttribute(ctypes.byref(major), 75, dev)
        lib.cuDeviceGetAttribute(ctypes.byref(minor), 76, dev)
        mem = ctypes.c_size_t(0)
        if total_mem is not None:
            total_mem(ctypes.byref(mem), dev)
        info["gpus"].append({
            "name": name.value.decode("utf-8", "replace").strip(),
            "cc": (major.value, minor.value),
            "memory_mb": int(mem.value // (1024 * 1024)),
        })
    return info


def _fmt_cuda_version(v: int) -> str:
    """13040 -> "13.4" (the CUDA driver API's version encoding)."""
    return f"{v // 1000}.{(v % 1000) // 10}" if v > 0 else ""


# ---- one answer: can the bundled engine use the GPU, and if not, why? -------------

# CTranslate2's wheels (4.4 - 4.8.2, read from their embedded GPU code) carry
# precompiled GPU code up to compute capability 8.6 plus portable compute_86
# PTX. Precompiled code runs on any GPU of the same major version (8.x, e.g. the
# RTX 40 series). A newer major (9.x Hopper, 10.x/12.x Blackwell, e.g. the RTX
# 50 series) runs the PTX, which the NVIDIA driver compiles on first use.
_CT2_NEWEST_PRECOMPILED_CC_MAJOR = 8


@dataclass(frozen=True)
class CudaStatus:
    """Whether the bundled engine can run on an NVIDIA GPU here -- and if not, why.

    ``gpu_present`` separates "there is an NVIDIA GPU but it cannot be used"
    (actionable: ``reason`` + ``fix`` say what to do) from "there is no NVIDIA
    GPU" (nothing to fix).
    """

    usable: bool
    gpu_present: bool
    reason: str = ""
    fix: str = ""
    note: str = ""
    gpu_name: str = ""
    compute_capability: str = ""
    memory_mb: int = 0
    driver_cuda_version: str = ""
    device_count: int = 0
    compute_types: tuple[str, ...] = ()
    missing_libs: tuple[str, ...] = ()
    can_install_runtime: bool = False

    def summary(self) -> str:
        """One or two sentences for a status line or a log entry."""
        if self.usable:
            head = f"{self.gpu_name or 'NVIDIA GPU'}: CUDA ready."
            return f"{head} {self.note}".strip()
        return " ".join(p for p in (self.reason, self.fix) if p)


def cuda_status() -> CudaStatus:
    """Check the whole CUDA chain and say what (if anything) is broken.

    Driver + GPU -> CTranslate2 sees the device -> supported compute types ->
    the CUDA runtime libraries load. Single source of truth for the Hardware
    wizard, the device auto-pick, the persisted-choice revalidation and the
    CPU warning. Never raises.
    """
    try:
        return _cuda_status()
    except Exception as e:  # noqa: BLE001 -- a diagnostic must never raise
        logger.exception("CUDA status check failed")
        return CudaStatus(
            usable=False, gpu_present=False,
            reason=f"The GPU check itself failed: {e}",
        )


def _cuda_status() -> CudaStatus:
    if sys.platform == "darwin":
        return CudaStatus(
            usable=False, gpu_present=False,
            reason="NVIDIA CUDA is not available on macOS.",
        )
    driver = _run_with_timeout(_cuda_driver_info, _CUDA_DRIVER_PROBE_TIMEOUT_S, {})
    gpus = list(driver.get("gpus") or [])
    first: dict[str, Any] = gpus[0] if gpus else {}
    cc = tuple(first.get("cc") or ())
    driver_version = int(driver.get("driver_version") or 0)
    gpu_name = str(first.get("name") or "")
    info: dict[str, Any] = {
        "gpu_name": gpu_name,
        "compute_capability": f"{cc[0]}.{cc[1]}" if len(cc) == 2 else "",
        "memory_mb": int(first.get("memory_mb") or 0),
        "driver_cuda_version": _fmt_cuda_version(driver_version),
    }
    driver_fix = (
        "Update the NVIDIA graphics driver (nvidia.com/drivers), restart the "
        "app and open this window again. If it still fails, click 'Copy "
        "diagnostics' and attach the text to a GitHub issue."
    )

    try:
        import ctranslate2  # type: ignore[import-not-found]
    except Exception as e:  # noqa: BLE001
        return CudaStatus(
            usable=False, gpu_present=bool(gpus),
            reason=f"The transcription engine (CTranslate2) could not be loaded: {e}",
            fix="Reinstall the app.", **info,
        )
    version = _ct2_version(ctranslate2)
    count = _ct2_cuda_device_count(ctranslate2)
    if count <= 0:
        if not gpus:
            return CudaStatus(
                usable=False, gpu_present=False,
                reason="No NVIDIA CUDA GPU was found.", **info,
            )
        needed = 11 if version and version < (4,) else 12
        if driver_version and driver_version // 1000 < needed:
            return CudaStatus(
                usable=False, gpu_present=True,
                reason=(
                    f"The NVIDIA driver is too old: it supports CUDA "
                    f"{info['driver_cuda_version']}, the transcription engine "
                    f"needs CUDA {needed}."
                ),
                fix=driver_fix, **info,
            )
        return CudaStatus(
            usable=False, gpu_present=True,
            reason=(
                f"The NVIDIA driver reports {gpu_name or 'a GPU'}, but the "
                "transcription engine (CTranslate2 "
                f"{'.'.join(map(str, version)) or '?'}) cannot open it."
            ),
            fix=driver_fix, **info,
        )
    try:
        compute_types = tuple(sorted(ctranslate2.get_supported_compute_types("cuda")))
    except Exception as e:  # noqa: BLE001
        return CudaStatus(
            usable=False, gpu_present=True,
            reason=f"The transcription engine found the GPU but could not query it: {e}",
            fix=driver_fix, device_count=count, **info,
        )
    # ONE runtime-library probe per check, shared by the verdict and the
    # explanation: two probes could disagree (the first timing out on an
    # antivirus scan, the second finding the now-cached DLL) and doubled the
    # worst-case wait.
    report = _cuda_runtime_report(version)
    if not (report and all(report.values())):
        return _missing_runtime_status(version, count, compute_types, info, report)
    note = ""
    if len(cc) == 2 and cc[0] > _CT2_NEWEST_PRECOMPILED_CC_MAJOR:
        note = (
            f"This GPU (compute capability {info['compute_capability']}) is "
            "newer than the GPU code the engine ships precompiled, so the "
            "NVIDIA driver compiles it on first use: the first GPU run can "
            "take noticeably longer; later runs reuse the driver's cache."
        )
    return CudaStatus(
        usable=True, gpu_present=True, note=note,
        device_count=count, compute_types=compute_types, **info,
    )


def _missing_runtime_status(
    version: tuple[int, ...],
    count: int,
    compute_types: tuple[str, ...],
    info: dict[str, Any],
    report: dict[str, str | None] | None,
) -> CudaStatus:
    """CudaStatus for "GPU fine, CUDA runtime library missing"."""
    required = _required_cuda_libs(version)
    if report is None:
        return CudaStatus(
            usable=False, gpu_present=True,
            reason=(
                "Loading the NVIDIA CUDA libraries did not finish in time "
                "(an antivirus scan of the large cuBLAS files, or a broken "
                "CUDA install)."
            ),
            fix="Click Re-probe to try again.",
            device_count=count, compute_types=compute_types, **info,
        )
    families = [f for f in required if not report.get(f)]
    missing = tuple(required[f][0] for f in families)
    packages = _pip_packages_for(families, version)
    can_install = (
        families == ["cuBLAS"] and packages == [CUDA_RUNTIME_PIP_PACKAGE]
        and sys.platform in ("win32", "linux")
    )
    fix = (
        "Click 'Install GPU support' below (a one-time download of NVIDIA's "
        "cuBLAS library, about 550 MB), or run "
        f"`python -m pip install {' '.join(packages)}` with this app's Python."
        if can_install else
        f"Run `python -m pip install {' '.join(packages)}` with this app's "
        "Python, or install the NVIDIA CUDA Toolkit, then click Re-probe."
    )
    return CudaStatus(
        usable=False, gpu_present=True,
        reason=(
            f"The GPU was found, but the NVIDIA {' and '.join(families)} library "
            f"it needs ({', '.join(missing)}) is not installed -- the "
            "graphics driver does not include it."
        ),
        fix=fix, device_count=count, compute_types=compute_types,
        missing_libs=missing, can_install_runtime=can_install, **info,
    )


def classify_cuda_load_failure(exc_text: str) -> str:
    """Classify a failed CUDA ``WhisperModel`` load / warm-up from its exception
    text, so the self-healing fallback (see ``core.transcriber`` and
    ``core.backends.faster_whisper_be``) can log/report an accurate reason
    instead of always blaming missing runtime libraries.

    Returns one of:

      * ``"arch_unsupported"`` -- the GPU code in the installed CUDA libraries
        cannot run on this GPU ("no kernel image", "invalid device function"):
        typically a GPU generation newer than the libraries (reported for an
        RTX 50-series/Blackwell ``sm_120`` laptop GPU in GitHub issue #7) or a
        driver too old to compile the portable PTX for it.
      * ``"out_of_memory"`` -- the model does not fit in the GPU's memory.
      * ``"runtime_libs"`` -- missing/broken CUDA runtime libraries (cuBLAS,
        and cuDNN for CTranslate2 < 4.6.3).
      * ``"unknown"`` -- matches no known pattern; the caller falls back to the
        generic runtime-libraries message.

    Heuristic and best-effort only -- a misclassification only changes which
    explanatory sentence is logged/shown; the fallback-to-CPU behaviour itself
    is identical in every case.
    """
    text = exc_text.lower()
    arch_markers = (
        "no kernel image",
        "invalid device function",
        "cuda capability",
        "is not compatible with the current",
        "compute capability",
        "arch_mismatch",
        "architecture mismatch",
    )
    if any(m in text for m in arch_markers):
        return "arch_unsupported"
    if "out of memory" in text or "alloc_failed" in text:
        return "out_of_memory"
    lib_markers = (
        "cudnn", "cublas", "dll", "shared object", "cannot open",
        "unable to load", "is not found", "no such file",
    )
    if any(m in text for m in lib_markers):
        return "runtime_libs"
    return "unknown"


_ARCH_UNSUPPORTED_REASON = (
    "This usually means the GPU code in the installed CUDA libraries cannot "
    "run on this GPU yet (common for a brand-new NVIDIA generation) -- NOT "
    "that the runtime is missing or the model is corrupt. Update the NVIDIA "
    "driver first (it compiles code for new GPUs), then update the engine's "
    "CUDA libraries inside this app's Python environment: `python -m pip "
    "install --upgrade ctranslate2 nvidia-cublas-cu12`."
)
_OUT_OF_MEMORY_REASON = (
    "The model does not fit in the GPU's memory -- pick a smaller model (or "
    "close other programs using the GPU); the model itself is fine."
)
_RUNTIME_LIBS_REASON = (
    "This usually means the NVIDIA cuBLAS runtime library (cuDNN too for "
    "older engine builds) is missing or broken, NOT that the model is "
    "corrupt. Advanced > Re-detect hardware can install it."
)


def cuda_load_failure_reason(exc_text: str) -> str:
    """Human-readable explanation sentence for a failed CUDA load, picked via
    :func:`classify_cuda_load_failure`. Shared by both self-healing call
    sites so their log/status messages can't drift apart again."""
    kind = classify_cuda_load_failure(exc_text)
    if kind == "arch_unsupported":
        return _ARCH_UNSUPPORTED_REASON
    if kind == "out_of_memory":
        return _OUT_OF_MEMORY_REASON
    return _RUNTIME_LIBS_REASON


def warm_up_cuda_model(model: Any) -> None:
    """Run one small real encoder pass on a freshly built CUDA model.

    CTranslate2 loads cuBLAS and runs its first GPU kernels lazily -- at the
    first forward pass, not in ``WhisperModel(...)``. A missing cuBLAS, GPU code
    that cannot run on this GPU ("no kernel image"), or running out of memory
    therefore only surfaced at the user's first transcription, after the load's
    CUDA->CPU self-heal had already reported success. One encoder pass here
    moves those failures into the load, where both self-healing loaders catch
    them and fall back to CPU.

    Raises what the GPU pass raises (CTranslate2 raises RuntimeError). Being
    unable to build the input (a faster-whisper API difference) is logged and
    skipped instead -- that says nothing about the GPU and must not cause a
    CPU downgrade.
    """
    try:
        import numpy as np
        from faster_whisper.audio import pad_or_trim  # type: ignore[import-not-found]
        features = pad_or_trim(model.feature_extractor(np.zeros(16000, dtype=np.float32)))
        encode = model.encode
    except Exception as e:  # noqa: BLE001
        logger.info("CUDA warm-up skipped (%s: %s)", type(e).__name__, e)
        return
    t0 = time.monotonic()
    try:
        encode(features)
    except (TypeError, ValueError) as e:
        logger.info("CUDA warm-up skipped (%s: %s)", type(e).__name__, e)
        return
    logger.info("CUDA warm-up pass ok in %.1fs", time.monotonic() - t0)


def cuda_load_ok() -> bool:
    """Cheap self-test: can the bundled backend actually load a CUDA model?

    True only when CTranslate2 sees a CUDA device AND the CUDA runtime
    libraries it needs load. Never raises (callers run it at startup).
    """
    return cuda_status().usable


def _gpu_name() -> str:
    """Best-effort NVIDIA GPU name: the driver API, else an already-imported
    torch (never imported here -- it takes seconds); "NVIDIA GPU" if unknown."""
    info = _run_with_timeout(_cuda_driver_info, _CUDA_DRIVER_PROBE_TIMEOUT_S, {})
    for gpu in info.get("gpus") or []:
        if gpu.get("name"):
            return str(gpu["name"])
    torch: Any = sys.modules.get("torch")
    try:
        if torch is not None and torch.cuda.is_available():
            return str(torch.cuda.get_device_name(0))
    except Exception:  # noqa: BLE001
        pass
    return "NVIDIA GPU"


def _cpu_name() -> str:
    try:
        import platform
        return platform.processor() or platform.machine() or "CPU"
    except Exception:  # noqa: BLE001
        return "CPU"


def _probe_cuda(status: CudaStatus | None = None) -> list[Tier]:
    """Return ordered list of CUDA-backed tiers actually supported.

    Built from :func:`cuda_status`, so a GPU is offered only when CTranslate2
    sees it AND the CUDA runtime libraries load (selecting CUDA otherwise used
    to make the first transcription hard-fail). Never raises.
    """
    status = cuda_status() if status is None else status
    if not status.usable:
        if status.gpu_present:
            logger.info(
                "NVIDIA GPU present but CUDA not usable: %s source=cuda_probe",
                status.summary(),
            )
        return []
    gpu = status.gpu_name or _gpu_name()
    supported = set(status.compute_types)
    tiers: list[Tier] = []
    if "float16" in supported:
        tiers.append(Tier(
            slug="cuda_float16",
            label=f"NVIDIA CUDA (float16) — {gpu}",
            device="cuda",
            compute_type="float16",
            detail=gpu,
        ))
    if "int8_float16" in supported:
        tiers.append(Tier(
            slug="cuda_int8_float16",
            label=f"NVIDIA CUDA (int8+float16) — {gpu}",
            device="cuda",
            compute_type="int8_float16",
            detail=gpu,
        ))
    return tiers


def _probe_qnn_npu() -> list[Tier]:
    """Snapdragon X NPU via onnxruntime QNN execution provider.

    Detected here so the wizard can show "available — switch backend
    to use" even though the bundled faster_whisper backend can't
    drive QNN directly. The user enables it by installing the matching
    backend in a future release.
    """
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]
        provs = list(ort.get_available_providers())
        if "QNNExecutionProvider" in provs:
            return [Tier(
                slug="qnn_npu",
                label="Snapdragon X NPU (QNN) — backend not bundled",
                device="cpu",
                compute_type="int8",
                backend="qnn_npu",
                detail="QNN provider detected via onnxruntime",
            )]
    except Exception:  # noqa: BLE001
        pass
    return []


def _probe_openvino() -> list[Tier]:
    """Intel NPU + Intel/AMD GPU via OpenVINO."""
    tiers: list[Tier] = []
    try:
        import openvino as ov  # type: ignore[import-not-found]
        core = ov.Core()
        devices = list(core.available_devices)
        for dev in devices:
            up = dev.upper()
            if up.startswith("NPU"):
                tiers.append(Tier(
                    slug="openvino_npu",
                    label=f"Intel NPU (OpenVINO {dev}) — backend not bundled",
                    device="cpu",
                    compute_type="int8",
                    backend="openvino_npu",
                    detail=f"OpenVINO device {dev}",
                ))
            elif up.startswith("GPU"):
                tiers.append(Tier(
                    slug="openvino_gpu",
                    label=f"GPU via OpenVINO ({dev}) — backend not bundled",
                    device="cpu",
                    compute_type="int8",
                    backend="openvino_gpu",
                    detail=f"OpenVINO device {dev}",
                ))
    except Exception:  # noqa: BLE001
        pass
    return tiers


def _probe_directml() -> list[Tier]:
    """DirectML execution provider — Windows GPU path for AMD/Intel."""
    try:
        import onnxruntime as ort  # type: ignore[import-not-found]
        provs = list(ort.get_available_providers())
        if "DmlExecutionProvider" in provs:
            return [Tier(
                slug="directml",
                label="DirectML GPU (Windows DX12) — backend not bundled",
                device="cpu",
                compute_type="int8",
                backend="directml",
                detail="DML provider detected via onnxruntime",
            )]
    except Exception:  # noqa: BLE001
        pass
    return []


def _probe_cpu() -> list[Tier]:
    cpu = _cpu_name()
    return [Tier(
        slug="cpu_int8",
        label=f"CPU int8 (universal fallback) — {cpu}",
        device="cpu",
        compute_type="int8",
        detail=cpu,
    )]


def probe_tiers(cuda: CudaStatus | None = None) -> list[Tier]:
    """Return every tier the current host supports, best → worst.

    CPU int8 is always last and always present so the list is never
    empty; callers can rely on ``tiers[-1]`` as a guaranteed fallback.

    app.widgets.hardware_wizard runs this on a fresh daemon thread per
    re-probe click, and each of the sub-probes below does its own first
    import of a heavy C-extension package (ctranslate2, onnxruntime,
    torch) -- see core/_gc_import_guard.py for why the whole call runs
    under a shared, process-wide GC-disable guard.
    """
    with gc_disabled_import():
        tiers: list[Tier] = []
        # A caller that already ran cuda_status() (the wizard shows its
        # reason too) passes it, so the CUDA chain is probed only once.
        tiers.extend(_probe_cuda(cuda) if cuda is not None else _probe_cuda())
        tiers.extend(_probe_qnn_npu())
        tiers.extend(_probe_openvino())
        tiers.extend(_probe_directml())
        tiers.extend(_probe_cpu())
        return tiers


def first_supported_tier(tiers: list[Tier]) -> Tier:
    """Pick the highest-ranked tier the bundled faster_whisper backend
    can actually drive today. Non-FW tiers (QNN / OpenVINO / DirectML)
    are surfaced in the UI but not auto-selected.
    """
    for t in tiers:
        if t.backend == "faster_whisper":
            return t
    return tiers[-1]


# ---------------------------------------------------------------- persistence


def save_hardware_choice(
    tier: Tier,
    *,
    benchmark_rtf: float | None = None,
) -> Path:
    """Write ``hardware.json`` atomically and return the path."""
    payload: dict[str, Any] = {
        "version": HARDWARE_FILE_VERSION,
        "detected_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "tier": tier.slug,
        "tier_label": tier.label,
        "device": tier.device,
        "compute_type": tier.compute_type,
        "backend": tier.backend,
        "benchmark_rtf": benchmark_rtf,
        "hardware_summary": tier.detail,
        "probe_version": HARDWARE_PROBE_VERSION,
    }
    path = hardware_json_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(path) + ".tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    logger.info(
        "hardware.json saved: tier=%s device=%s compute_type=%s",
        tier.slug, tier.device, tier.compute_type,
    )
    return path


def load_hardware_choice() -> dict[str, Any] | None:
    """Read ``hardware.json``; return None on any error.

    A bad file is renamed to ``.corrupt`` so the auto-probe path can
    recreate it cleanly on the next wizard run, mirroring the
    config.json corruption handling.
    """
    path = hardware_json_path()
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("hardware.json is not a JSON object")
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as e:
        logger.exception("Could not read %s (%s); ignoring", path, e)
        try:
            os.replace(path, str(path) + ".corrupt")
        except OSError:
            pass
        return None
    return data


def device_choice_from_hardware_file() -> tuple[str, str] | None:
    """Return ``(device, compute_type)`` from ``hardware.json``, or None.

    Used by :func:`core.transcriber.detect_device` to honour the
    wizard's persisted choice before falling back to the auto-probe.
    Returns None when:

      * the file is missing or unreadable
      * the recorded tier is for a non-bundled backend
      * a non-CUDA choice was saved by probe version 1, which could never
        see a CUDA GPU (issue #7) -- that "choice" was the only option
        offered, not a preference, so the fixed probe decides again
      * the wizard picked CUDA but CUDA is not usable now (laptop dock
        unplug, driver uninstall, CUDA runtime library removed)
    """
    data = load_hardware_choice()
    if not data:
        return None
    device = str(data.get("device") or "").strip()
    compute_type = str(data.get("compute_type") or "").strip()
    if not device or not compute_type:
        return None
    backend = str(data.get("backend") or "faster_whisper")
    if backend != "faster_whisper":
        return None
    try:
        probe_version = int(data.get("probe_version") or 1)
    except (TypeError, ValueError):
        probe_version = 1
    if device != "cuda" and probe_version < HARDWARE_PROBE_VERSION:
        logger.info(
            "hardware.json picks %s/%s but was saved by an older hardware "
            "probe that could not detect NVIDIA GPUs; re-probing instead.",
            device, compute_type,
        )
        return None
    if device == "cuda":
        # Honouring CUDA when it is no longer usable would hand a doomed
        # device to the model loader; fall back to the auto-probe instead.
        status = cuda_status()
        if not status.usable:
            logger.info(
                "hardware.json picks CUDA but CUDA is not usable now (%s); "
                "falling back to auto-probe.", status.summary(),
            )
            return None
        if status.compute_types and compute_type not in status.compute_types:
            # CTranslate2 raises for an unsupported explicit compute type
            # (e.g. int8 on a GPU generation where it is disabled).
            best = next(
                (ct for ct in ("float16", "int8_float16", "int8")
                 if ct in status.compute_types),
                None,
            )
            if best is None:
                return None
            logger.info(
                "hardware.json picks cuda/%s, which this GPU does not "
                "support; using cuda/%s.", compute_type, best,
            )
            compute_type = best
    return device, compute_type


def tier_to_dict(tier: Tier) -> dict[str, Any]:
    """Dataclass → dict for tests and serialization."""
    return asdict(tier)


# ---------------------------------------------------------------- detect_device
#
# v0.8 audit A7: this used to live in two places (core/transcriber.py
# and core/backends/faster_whisper_be.py) with slightly drifting
# logic. Both call sites now delegate to ``detect_device_for(config)``
# below so the resolution chain stays in one place.


def detect_device_for(config: dict[str, Any]) -> tuple[str, str]:
    """Return ``(device, compute_type)`` for a given config dict.

    Resolution order — first match wins, every match logs the source:

      1. Explicit ``config["device"]`` setting (anything ≠ ``"auto"``).
      2. The Hardware Wizard's persisted choice in ``hardware.json``
         when it picks a tier the bundled backend can drive AND the
         hardware is still present.
      3. :func:`cuda_status` -- CTranslate2 sees a GPU and the CUDA
         runtime libraries load (which also prepares them for the load).
      4. CPU with the configured compute_type.

    There is deliberately no ``torch.cuda.is_available()`` fallback any
    more: the engine is CTranslate2, and a torch that sees the GPU says
    nothing about whether CTranslate2 can use it.
    """
    if config.get("device") != "auto":
        dev = config.get("device", "cpu")
        ct = config.get("compute_type", "int8")
        logger.info(
            "device_choice device=%s compute_type=%s source=config", dev, ct
        )
        return dev, ct
    try:
        wizard_choice = device_choice_from_hardware_file()
        if wizard_choice is not None:
            logger.info(
                "device_choice device=%s compute_type=%s source=hardware.json",
                wizard_choice[0], wizard_choice[1],
            )
            return wizard_choice
    except Exception:
        logger.exception("device_choice_from_hardware_file probe raised")
    status = cuda_status()
    if status.usable:
        for ct in ("float16", "int8_float16", "int8"):
            if ct in status.compute_types:
                logger.info(
                    "device_choice device=cuda compute_type=%s "
                    "source=ctranslate2_probe gpu=%s", ct, status.gpu_name or "?",
                )
                return "cuda", ct
    elif status.gpu_present:
        logger.warning(
            "NVIDIA GPU found but CUDA is not usable, using the CPU: %s",
            status.summary(),
        )
    ct = config.get("compute_type", "int8")
    logger.info(
        "device_choice device=cpu compute_type=%s source=cpu_fallback", ct
    )
    return "cpu", ct


# ---------------------------------------------------------------- model advice
#
# "Pick the best model for my PC" (owner idea, 2026-09-23). The device pick
# above says WHERE to run; this says WHICH Whisper model fits that hardware.
# Thresholds are deliberately conservative and come from real runs: on the
# 4-core i7-6700 dev box (CPU int8, 8 s of speech) small took 4 s, medium
# 12 s, large-v3-turbo 17 s and large-v3 19 s; large-v3 in float16 plus the
# batched pipeline needs roughly 5-6 GB of VRAM, turbo about half that.


@dataclass(frozen=True)
class ModelPick:
    """One recommended model: ``kind`` is "fastest" or "accurate"."""

    kind: str
    slug: str
    reason: str


def system_ram_gb() -> float:
    """Total physical memory in GB; 0.0 when it cannot be read."""
    try:
        import psutil  # type: ignore[import-not-found]
        return float(psutil.virtual_memory().total) / 1024 ** 3
    except Exception:  # noqa: BLE001
        pass
    sysconf: Any = getattr(os, "sysconf", None)  # POSIX only; psutil covers Windows
    if sysconf is None:
        return 0.0
    try:
        return float(sysconf("SC_PHYS_PAGES") * sysconf("SC_PAGE_SIZE")) / 1024 ** 3
    except (ValueError, OSError):
        return 0.0


def recommend_models(
    status: CudaStatus | None = None,
    *,
    ram_gb: float | None = None,
    cpu_cores: int | None = None,
) -> list[ModelPick]:
    """Fastest + most accurate Whisper model for this machine.

    Uses the GPU's memory when CUDA is usable, else CPU cores and RAM. When
    both picks are the same model, one "accurate" pick is returned.
    """
    status = cuda_status() if status is None else status
    if status.usable:
        vram_gb = status.memory_mb / 1024 if status.memory_mb else 0.0
        gpu = status.gpu_name or "your NVIDIA GPU"
        if vram_gb == 0.0 or vram_gb >= 7.5:
            fastest = ModelPick(
                "fastest", "large-v3-turbo",
                f"Runs on {gpu}: several times faster than Large v3 with "
                "nearly the same accuracy.",
            )
            accurate = ModelPick(
                "accurate", "large-v3" if vram_gb else "large-v3-turbo",
                f"The most accurate model; {gpu} has enough memory for it."
                if vram_gb else
                f"Runs on {gpu}; its memory size is unknown, so the lighter "
                "large model is the safe choice.",
            )
        elif vram_gb >= 3.5:
            fastest = accurate = ModelPick(
                "accurate", "large-v3-turbo",
                f"Near-best accuracy that still fits in the {vram_gb:.0f} GB "
                f"of {gpu}; Large v3 would be tight.",
            )
        else:
            fastest = ModelPick(
                "fastest", "small",
                f"Fits easily in the {vram_gb:.0f} GB of {gpu}.",
            )
            accurate = ModelPick(
                "accurate", "medium",
                f"The largest model that fits comfortably in {vram_gb:.0f} GB.",
            )
    else:
        cores = cpu_cores if cpu_cores is not None else (os.cpu_count() or 0)
        ram = system_ram_gb() if ram_gb is None else ram_gb
        weak = (0 < ram < 7.5) or (0 < cores < 4)
        if weak:
            fastest = ModelPick(
                "fastest", "base",
                "Runs on the CPU; quick even on a modest computer.",
            )
            accurate = ModelPick(
                "accurate", "small",
                "Clearly better than Base and still usable on this computer's "
                "CPU and memory.",
            )
        else:
            fastest = ModelPick(
                "fastest", "small",
                "Runs on the CPU faster than real time on a typical 4-core "
                "computer.",
            )
            accurate = ModelPick(
                "accurate", "large-v3-turbo",
                "Near-best accuracy; on the CPU it takes roughly twice the "
                "audio's length on a typical 4-core computer (faster with "
                "more cores).",
            )
    if fastest.slug == accurate.slug:
        return [accurate]
    return [fastest, accurate]


def diagnostics_report() -> str:
    """Plain-text GPU/CUDA report for bug reports. Never raises.

    Shown by the Hardware wizard's "Copy diagnostics" button and printed by
    ``python -m core.hardware`` (run from the app folder with the app's own
    Python). It lists every link of the chain :func:`cuda_status` checks, so
    one paste from a user's machine shows which one breaks.
    """
    lines: list[str] = []
    add = lines.append

    def _safe(label: str, fn: Callable[[], Any]) -> None:
        try:
            add(f"{label}: {fn()}")
        except Exception as e:  # noqa: BLE001
            add(f"{label}: <error: {type(e).__name__}: {e}>")

    import platform
    add("== Whisper Transcriber Suite GPU diagnostics ==")
    try:
        from . import __version__ as app_version
    except Exception:  # noqa: BLE001
        app_version = "?"
    add(f"App version: {app_version}")
    add(f"Python: {sys.version.split()[0]} ({sys.executable})")
    _safe("Platform", platform.platform)

    add("")
    add("-- NVIDIA driver (CUDA driver API) --")
    driver = _run_with_timeout(_cuda_driver_info, _CUDA_DRIVER_PROBE_TIMEOUT_S, {})
    if not driver:
        add("No NVIDIA driver answered (nvcuda.dll / libcuda.so.1 missing or cuInit failed).")
    else:
        add(f"Driver supports CUDA: {_fmt_cuda_version(int(driver.get('driver_version') or 0)) or '?'}")
        for i, gpu in enumerate(driver.get("gpus") or []):
            cc = gpu.get("cc") or (0, 0)
            add(
                f"GPU {i}: {gpu.get('name')} | compute capability "
                f"{cc[0]}.{cc[1]} | {gpu.get('memory_mb')} MB"
            )

    add("")
    add("-- CTranslate2 (transcription engine) --")
    ct2: Any = None
    try:
        import ctranslate2  # type: ignore[import-not-found]
        ct2 = ctranslate2
        add(f"Version: {getattr(ct2, '__version__', '?')} ({getattr(ct2, '__file__', '?')})")
        _safe("get_cuda_device_count()", lambda: _ct2_cuda_device_count(ct2))
        _safe("CUDA compute types", lambda: sorted(ct2.get_supported_compute_types("cuda")))
        _safe("CPU compute types", lambda: sorted(ct2.get_supported_compute_types("cpu")))
    except Exception as e:  # noqa: BLE001
        add(f"Import failed: {type(e).__name__}: {e}")

    add("")
    add("-- CUDA runtime libraries --")
    version = _ct2_version(ct2) if ct2 is not None else ()
    report = _cuda_runtime_report(version)
    for family, names in _required_cuda_libs(version).items():
        where = (report or {}).get(family)
        add(f"{family} ({' / '.join(names)}): {where or 'NOT FOUND'}")
    if report is None:
        add("(loading timed out)")
    add("Folders searched: " + ("; ".join(cuda_library_dirs()) or "(none exist)"))
    try:
        import importlib.metadata as _md
        for dist in ("torch", CUDA_RUNTIME_PIP_PACKAGE, "nvidia-cudnn-cu12", "faster-whisper"):
            try:
                add(f"{dist}: {_md.version(dist)}")
            except _md.PackageNotFoundError:
                add(f"{dist}: not installed")
    except Exception:  # noqa: BLE001
        pass

    add("")
    add("-- Verdict --")
    status = cuda_status()
    add(f"CUDA usable: {status.usable}")
    add(f"GPU present: {status.gpu_present}")
    for label, value in (("Reason", status.reason), ("Fix", status.fix), ("Note", status.note)):
        if value:
            add(f"{label}: {value}")
    try:
        data = load_hardware_choice()
        add(f"hardware.json: {json.dumps(data) if data else '(none)'}")
    except Exception as e:  # noqa: BLE001
        add(f"hardware.json: <error: {e}>")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover - manual diagnostics entry point
    print(diagnostics_report())
