"""Directory aliases for packaging fixtures without changing Windows privileges."""
import os
from pathlib import Path
import subprocess

WINDOWS = os.name == "nt"


def directory_alias(alias: Path, target: Path) -> None:
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError as error:
        if not WINDOWS or getattr(error, "winerror", None) != 1314:
            raise
        # Junctions need no symlink privilege. Paths remain environment data,
        # never interpolated into PowerShell code or passed to another shell.
        environment = os.environ.copy()
        environment.update(WTS_TEST_ALIAS=str(alias.absolute()), WTS_TEST_TARGET=str(target.resolve()))
        executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        command = [str(executable), "-NoLogo", "-NoProfile", "-NonInteractive", "-Command",
                   "$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:WTS_TEST_ALIAS -Target $env:WTS_TEST_TARGET | Out-Null"]
        result = subprocess.run(command, env=environment, stdin=subprocess.DEVNULL,
                                capture_output=True, timeout=10,
                                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        if result.returncode != 0:
            raise OSError("Could not create the temporary directory junction") from error
    if not alias.is_dir() or alias.resolve() != target.resolve():
        raise OSError("Temporary directory alias did not resolve to its fixture")
