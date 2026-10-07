"""Smoke test of an installed Windows build, run with the INSTALLED interpreter:

  <install dir>\\python\\python.exe tools\\smoke_windows_install.py <install dir> <expected version>

Checks that the app's own packages load from the install dir (not from a source checkout), the
version matches, the bundled runtime stack imports, Tcl/Tk start, the bundled tools run, the
diarization models are found, and `gui.py --help` exits 0. Prints one line per check and exits 1
on the first failure. Used by .github/workflows/windows-installer.yml after a silent install.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    install = os.path.abspath(argv[0])
    expected = argv[1]
    sys.path.insert(0, install)
    os.chdir(install)

    def ok(msg: str) -> None:
        print(f"[smoke] ok: {msg}", flush=True)

    def fail(msg: str) -> int:
        print(f"[smoke] FAIL: {msg}", flush=True)
        return 1

    if not os.path.abspath(sys.executable).lower().startswith(install.lower() + os.sep):
        return fail(f"run with the installed python, not {sys.executable}")

    import core
    if not os.path.abspath(core.__file__).lower().startswith(install.lower() + os.sep):
        return fail(f"core imported from {core.__file__}, not from {install}")
    if core.__version__ != expected:
        return fail(f"core.__version__ is {core.__version__}, expected {expected}")
    ok(f"core {core.__version__} from {os.path.dirname(core.__file__)}")

    for name in ("faster_whisper", "ctranslate2", "av", "tokenizers", "sv_ttk", "tkinterdnd2",
                 "platformdirs", "docx", "reportlab", "sherpa_onnx", "psutil",
                 "core.transcriber", "core.worker", "core.server", "app"):
        try:
            importlib.import_module(name)
        except Exception as exc:  # report the exact import that broke, then stop
            return fail(f"import {name}: {type(exc).__name__}: {exc}")
    ok("runtime stack and app packages import")

    import tkinter
    root = tkinter.Tk()  # loads Tk too, not only Tcl (tkinter.Tcl() would pass without tk8.6)
    root.withdraw()
    root.update_idletasks()
    versions = f"Tcl {root.eval('info patchlevel')}, Tk {root.eval('package require Tk')}"
    root.destroy()
    ok(f"{versions} start")

    tools = {
        "ffmpeg.exe": (["-version"], "ffmpeg version"),
        "ffprobe.exe": (["-version"], "ffprobe version"),
        "yt-dlp.exe": (["--version"], "20"),
        "deno.exe": (["--version"], "deno "),
    }
    for exe, (args, needle) in tools.items():
        path = os.path.join(install, "bin", exe)
        proc = subprocess.run([path, *args], capture_output=True, text=True, timeout=120)
        first = (proc.stdout or proc.stderr).strip().splitlines()[:1]
        if proc.returncode != 0 or needle not in proc.stdout:
            return fail(f"{exe} {' '.join(args)} -> exit {proc.returncode}: {first}")
        ok(f"bin/{exe}: {first[0] if first else ''}")

    from core import diarization
    reason = diarization.availability_reason()
    if reason:
        return fail(f"diarization unavailable: {reason}")
    ok("diarization models found")

    proc = subprocess.run([sys.executable, os.path.join(install, "gui.py"), "--help"],
                          capture_output=True, text=True, timeout=300)
    if proc.returncode != 0 or "transcribe" not in proc.stdout:
        return fail(f"gui.py --help -> exit {proc.returncode}: {proc.stderr.strip()[-500:]}")
    ok("gui.py --help exits 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
