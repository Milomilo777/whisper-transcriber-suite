"""Measure the time from spawning WhisperTranscriberSuite.exe to its main window
becoming visible. Uses the Win32 EnumWindows API via ctypes so it has
no third-party dependencies.

Usage:
    python tools/measure_startup.py [path/to/WhisperTranscriberSuite.exe]

Default exe path: dist/WhisperTranscriberSuite.exe relative to repo root.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import subprocess
import sys
import time
from pathlib import Path


WINDOW_TITLE = "Transcription helper"


def _find_window_with_title(_target_pid: int, expected_title: str) -> int | None:
    """Find any visible window whose title matches expected_title.

    PID-matching is intentionally absent: the parent UI process spawns
    a standby worker, and on some PyInstaller builds the windowing
    thread can register under a slightly different PID than the one
    Popen handed us. Title is unique enough for this measurement.
    """
    user32 = ctypes.windll.user32  # type: ignore
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)  # type: ignore
    def callback(hwnd: int, _lparam: int) -> int:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        if buf.value != expected_title:
            return True
        found.append(hwnd)
        return False

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def measure(exe: Path, timeout_s: float = 1200.0) -> float | None:
    start = time.time()
    proc = subprocess.Popen([str(exe)], cwd=str(exe.parent))
    try:
        while time.time() - start < timeout_s:
            hwnd = _find_window_with_title(proc.pid, WINDOW_TITLE)
            if hwnd is not None:
                return time.time() - start
            time.sleep(0.1)
        return None
    finally:
        subprocess.run(
            ["taskkill", "/F", "/IM", "WhisperTranscriberSuite.exe"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        time.sleep(2)


def main() -> int:
    exe = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        Path(__file__).resolve().parent.parent / "dist" / "WhisperTranscriberSuite.exe"
    )
    if not exe.exists():
        print(f"exe not found: {exe}", file=sys.stderr)
        return 2
    print(f"measuring startup for {exe}")
    print(f"size: {exe.stat().st_size / (1024 * 1024):.1f} MB")

    runs: list[float] = []
    for i in range(3):
        elapsed = measure(exe)
        if elapsed is None:
            print(f"run {i + 1}: window did not appear within 1200 s")
            return 1
        print(f"run {i + 1}: {elapsed:.2f} s")
        runs.append(elapsed)

    runs.sort()
    print(f"median: {runs[len(runs) // 2]:.2f} s")
    print(f"min: {min(runs):.2f} s")
    print(f"max: {max(runs):.2f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
