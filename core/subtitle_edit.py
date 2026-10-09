"""Find Subtitle Edit on Windows and open a subtitle file in it.

Subtitle Edit (https://www.nikse.dk/subtitleedit) is a free subtitle editor with a waveform
view. The app does not build its own waveform editor; after a job the user can open the
written subtitle file there with one click.

Detection never searches the disk and never uses the network, and it needs no admin rights.
Order: the path the user set once in Advanced, then the uninstall registry entries, then the
usual install folders. Only Windows is supported: on other systems :func:`is_supported`
is False and the GUI hides the buttons.

Everything that touches the system (registry, environment, file checks, process start) is
injectable so the tests run without Subtitle Edit installed.
"""
from __future__ import annotations

import importlib
import ntpath
import os
import subprocess
import sys
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any

#: Config key holding the path to ``SubtitleEdit.exe`` ("" = auto-detect).
CONFIG_KEY = "subtitle_edit_path"

#: Official site, opened only when the user clicks the button and the editor is missing.
DOWNLOAD_URL = "https://www.nikse.dk/subtitleedit"

EXE_NAME = "SubtitleEdit.exe"
_FOLDER_NAME = "Subtitle Edit"

#: Subtitle formats Subtitle Edit opens that this app can write, best first.
SUBTITLE_EXTENSIONS: tuple[str, ...] = (".srt", ".vtt", ".ass", ".ssa", ".lrc")

_UNINSTALL_KEY = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"


def is_supported(platform: str | None = None) -> bool:
    """True where the button is offered (Windows only)."""
    return (platform or sys.platform) == "win32"


def pick_subtitle_file(paths: Iterable[str]) -> str | None:
    """The best subtitle file among ``paths``: SRT first, then VTT, ASS, SSA, LRC."""
    by_ext: dict[str, str] = {}
    for p in paths:
        ext = os.path.splitext(p)[1].lower()
        if ext in SUBTITLE_EXTENSIONS and ext not in by_ext:
            by_ext[ext] = p
    for ext in SUBTITLE_EXTENSIONS:
        if ext in by_ext:
            return by_ext[ext]
    return None


def sibling_subtitle_candidates(path: str) -> list[str]:
    """``path`` with each subtitle extension, for finding the file next to a transcript JSON."""
    base = os.path.splitext(path)[0]
    return [base + ext for ext in SUBTITLE_EXTENSIONS]


def registry_install_dirs() -> list[str]:
    """Install folders from the uninstall registry entries named "Subtitle Edit*".

    Reads HKLM (64- and 32-bit views) and HKCU; read-only, no admin rights needed.
    Returns [] when the registry is not available (not Windows).
    """
    try:
        # Loaded by name: the type stubs declare winreg's API on Windows only, and the
        # tests put a stand-in module in sys.modules.
        winreg: Any = importlib.import_module("winreg")
    except ImportError:
        return []
    dirs: list[str] = []
    views = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )
    for hive, view in views:
        try:
            root = winreg.OpenKey(hive, _UNINSTALL_KEY, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    name = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(root, name) as sub:
                        display = str(winreg.QueryValueEx(sub, "DisplayName")[0])
                        if not display.lower().startswith("subtitle edit"):
                            continue
                        for value in ("InstallLocation", "DisplayIcon", "UninstallString"):
                            try:
                                raw = str(winreg.QueryValueEx(sub, value)[0])
                            except OSError:
                                continue
                            folder = _folder_from_registry_value(raw, value)
                            if folder:
                                dirs.append(folder)
                except OSError:
                    continue
    return dirs


def _folder_from_registry_value(raw: str, value_name: str) -> str:
    """Turn a registry value into a folder: InstallLocation is one, the others name a file."""
    text = raw.strip().strip('"')
    if value_name != "InstallLocation":
        # DisplayIcon is "C:\\path\\SubtitleEdit.exe,0"; UninstallString may carry arguments.
        if text.startswith('"'):
            text = text[1:].split('"', 1)[0]
        lowered = text.lower()
        cut = lowered.find(".exe")
        text = text[: cut + 4] if cut != -1 else text
        # A registry value is always a Windows path, whatever platform parses it.
        return ntpath.dirname(text)
    return text


def program_dirs(env: Mapping[str, str] | None = None) -> list[str]:
    """The usual install folders, built from the environment."""
    env = os.environ if env is None else env
    dirs: list[str] = []
    for var in ("ProgramFiles", "ProgramW6432", "ProgramFiles(x86)"):
        root = env.get(var)
        if root:
            dirs.append(os.path.join(root, _FOLDER_NAME))
    local = env.get("LOCALAPPDATA")
    if local:
        dirs.append(os.path.join(local, "Programs", _FOLDER_NAME))
    return dirs


def configured_exe(
    user_path: str, *, isfile: Callable[[str], bool] = os.path.isfile,
) -> str | None:
    """``SubtitleEdit.exe`` at the configured path (the exe or its folder), or None.

    Quotes from "Copy as path" are dropped and ``%VARIABLES%`` expanded.
    """
    user_path = os.path.expandvars((user_path or "").strip().strip('"'))
    if not user_path:
        return None
    for candidate in (user_path, os.path.join(user_path, EXE_NAME)):
        if candidate.lower().endswith(".exe") and isfile(candidate):
            return candidate
    return None


def find_subtitle_edit(
    user_path: str = "",
    *,
    platform: str | None = None,
    registry: Callable[[], Sequence[str]] = registry_install_dirs,
    env: Mapping[str, str] | None = None,
    isfile: Callable[[str], bool] = os.path.isfile,
) -> str | None:
    """Path of ``SubtitleEdit.exe``, or None when it cannot be found.

    ``user_path`` may be the exe itself or the folder that holds it.
    """
    if not is_supported(platform):
        return None
    configured = configured_exe(user_path, isfile=isfile)
    if configured is not None:
        return configured
    try:
        registry_dirs = list(registry())
    except Exception:  # noqa: BLE001 - a registry hiccup must not hide the folder checks
        registry_dirs = []
    for folder in (*registry_dirs, *program_dirs(env)):
        candidate = os.path.join(folder, EXE_NAME)
        if isfile(candidate):
            return candidate
    return None


def build_command(exe: str, subtitle_path: str) -> list[str]:
    """Argument list for starting Subtitle Edit on one file.

    A list, never a shell string: Windows quotes each element itself, so paths with spaces
    and non-Latin letters arrive intact.
    """
    return [exe, subtitle_path]


def open_in_subtitle_edit(
    exe: str,
    subtitle_path: str,
    *,
    popen: Callable[..., object] = subprocess.Popen,
) -> None:
    """Start Subtitle Edit on ``subtitle_path`` without waiting for it.

    Raises ``FileNotFoundError`` when the subtitle file is missing and ``OSError`` when
    the program cannot be started.
    """
    if not os.path.isfile(subtitle_path):
        raise FileNotFoundError(subtitle_path)
    popen(
        build_command(exe, subtitle_path),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
