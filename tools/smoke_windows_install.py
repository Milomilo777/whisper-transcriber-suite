"""Smoke test of an installed Windows build, run with the INSTALLED interpreter:

  <install dir>\\python\\python.exe tools\\smoke_windows_install.py <install dir> <expected version>

Checks that the app's own packages load from the install dir (not from a source checkout), the
version matches, the bundled runtime stack and every app/core module import, the assets and the
licence files are present, Tcl/Tk start, the bundled tools run, the diarization models are found,
and `gui.py --help` exits 0. Also run on the Portable tree (embed_build). Prints one line per check and exits 1
on the first failure. Used by .github/workflows/windows-installer.yml after a silent install.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys

# Third-party runtime stack, including the GUI-only dependencies that the
# lazily imported app modules need (tray icon, folder watcher, microphone).
RUNTIME_MODULES = (
    "faster_whisper", "ctranslate2", "av", "tokenizers", "sv_ttk", "tkinterdnd2",
    "platformdirs", "docx", "reportlab", "arabic_reshaper", "bidi.algorithm",
    "sherpa_onnx", "psutil", "PIL.ImageTk", "pystray", "watchdog.observers", "sounddevice",
)

# Files the app opens at runtime: the window icon and the "Try it now" sample clip.
REQUIRED_ASSETS = (
    os.path.join("assets", "whisper.ico"),
    os.path.join("assets", "whisper.png"),
    os.path.join("assets", "sample_clip.mp3"),
    "LICENSE",
    "THIRD_PARTY_NOTICES.md",
)


# Filters "Make subtitled video" and "Burn subtitles" call (libass).
BURN_FILTERS = ("subtitles",)


def ffmpeg_missing_filters(ffmpeg: str, wanted: tuple[str, ...]) -> list[str]:
    """The names in *wanted* that ``ffmpeg -filters`` does not list."""
    proc = subprocess.run([ffmpeg, "-hide_banner", "-filters"], capture_output=True,
                          text=True, timeout=120)
    listed = {parts[1] for parts in (ln.split() for ln in (proc.stdout or "").splitlines())
              if len(parts) >= 3 and set(parts[0]) <= set(".TSC")}
    return [name for name in wanted if name not in listed]


def app_modules(root: str) -> list[str]:
    """Dotted names of every app.* / core.* module under ``root``, packages included."""
    names = []
    for top in ("app", "core"):
        for dirpath, dirnames, filenames in os.walk(os.path.join(root, top)):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            rel = os.path.relpath(dirpath, root).replace(os.sep, ".")
            for fn in sorted(filenames):
                if fn == "__init__.py":
                    names.append(rel)
                elif fn.endswith(".py"):
                    names.append(f"{rel}.{fn[:-3]}")
    return sorted(names)


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

    for name in RUNTIME_MODULES:
        try:
            importlib.import_module(name)
        except Exception as exc:  # report the exact import that broke, then stop
            return fail(f"import {name}: {type(exc).__name__}: {exc}")
    ok("runtime stack imports")

    # `gui.py --help` below never loads the GUI (app is imported lazily), so a
    # module with a missing dependency or an ImportError would pass. Import
    # every module the build ships instead.
    modules = app_modules(install)
    if len(modules) < 50:
        return fail(f"only {len(modules)} app/core modules found under {install}")
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception as exc:
            return fail(f"import {name}: {type(exc).__name__}: {exc}")
    ok(f"all {len(modules)} app/core modules import")

    missing = [rel for rel in REQUIRED_ASSETS if not os.path.isfile(os.path.join(install, rel))]
    if missing:
        return fail(f"assets missing: {missing}")
    icons = os.path.join(install, "assets", "icons")
    n_png = len([f for f in os.listdir(icons) if f.endswith(".png")])
    if n_png < 10:
        return fail(f"assets/icons holds only {n_png} PNG files")
    ok(f"assets present ({len(REQUIRED_ASSETS)} files + {n_png} icons)")

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

    # "Make subtitled video" and "Burn subtitles" need ffmpeg's subtitles filter
    # (libass); a build without it fails only when a user burns subtitles.
    missing = ffmpeg_missing_filters(os.path.join(install, "bin", "ffmpeg.exe"), BURN_FILTERS)
    if missing:
        return fail(f"bin/ffmpeg.exe lacks the {', '.join(missing)} filter (built without libass)")
    ok(f"bin/ffmpeg.exe has the {', '.join(BURN_FILTERS)} filter")

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
