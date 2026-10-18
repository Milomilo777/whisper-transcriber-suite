"""Portable host/RSS information and atomic local output helpers."""
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import platform
import sys
import tempfile
import wave


def windows_peak_rss_mb(handle=None):
    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    query = ctypes.WinDLL("psapi", use_last_error=True).GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(ProcessMemoryCounters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    if not query(handle if handle is not None else kernel.GetCurrentProcess(),
                 ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize / (1024 * 1024)


def peak_rss_mb():
    if sys.platform == "win32":
        return windows_peak_rss_mb(), "Windows PeakWorkingSetSize"
    try:
        import resource  # Unavailable on Windows; never imported there.
        own = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        child = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        scale = 1024 * 1024 if sys.platform == "darwin" else 1024
        return max(own, child) / scale, "ru_maxrss (max runner and CLI child)"
    except ImportError:
        return None, "unavailable"


def physical_ram_mb():
    if sys.platform == "win32":
        class MemoryStatus(ctypes.Structure):
            _fields_ = [("length", wintypes.DWORD), ("load", wintypes.DWORD)] + [
                (name, ctypes.c_ulonglong) for name in
                ("total_phys", "avail_phys", "total_page", "avail_page", "total_virtual", "avail_virtual", "extended")]
        status = MemoryStatus()
        status.length = ctypes.sizeof(status)
        query = ctypes.WinDLL("kernel32", use_last_error=True).GlobalMemoryStatusEx
        query.argtypes = [ctypes.POINTER(MemoryStatus)]
        if query(ctypes.byref(status)):
            return status.total_phys / (1024 * 1024)
        return None
    try:
        return os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024)
    except (AttributeError, OSError, ValueError):
        return None


def environment_info():
    cpu = platform.processor() or "unknown"
    governor = "unknown"
    if sys.platform.startswith("linux"):
        try:
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.startswith("model name"):
                    cpu = line.split(":", 1)[1].strip()
                    break
        except OSError:
            pass
        try:
            governor = Path("/sys/devices/system/cpu/cpu0/cpufreq/scaling_governor").read_text().strip()
        except OSError:
            pass
    return {"nproc": os.cpu_count(), "governor": governor, "cpu_model": cpu,
            "architecture": platform.machine(), "os": platform.system(),
            "ram_mb": physical_ram_mb(), "python": platform.python_version(),
            "affinity": sorted(os.sched_getaffinity(0)) if hasattr(os, "sched_getaffinity") else "uncontrolled",
            "statistics": {"bootstrap_resamples": 1000, "seed": 1234},
            "measurement": {"warmup_calls": 1, "repeats": 3, "mb_bytes": 1024 * 1024}}


def audio_duration(path):
    with wave.open(str(path), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 16000, "NONE"):
            raise ValueError(f"Expected 16 kHz mono PCM16 WAV: {path}")
        if audio.getnframes() == 0:
            raise ValueError(f"Empty WAV: {path}")
        return audio.getnframes() / audio.getframerate()


def write_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                         dir=path.parent, delete=False) as output:
            temporary = Path(output.name)
            output.write(text)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def write_json(path, data):
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
