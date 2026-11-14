"""Disposable process boundary for UI hardware checks and native diagnostics."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from typing import Any

_PROBE_LOCK = threading.Lock()
_UNREAPED_PROCESS: subprocess.Popen[Any] | None = None
PROBE_TIMEOUT_S = 25.0
MAX_RESULT_BYTES = 2 * 1024 * 1024


def _command(operation: str, result: Path) -> list[str]:
    args = [operation, str(result)]
    if getattr(sys, "frozen", False):
        return [sys.executable, "--hardware-probe-worker", *args]
    # Embedded Python ignores PYTHONPATH. Pass the trusted source root as an
    # argument to constant code, rather than interpolating it into Python code.
    root = str(Path(__file__).resolve().parents[1])
    bootstrap = ("import sys;sys.path.insert(0,sys.argv.pop(1));"
                 "from core.hardware_probe import worker_main;worker_main()")
    return [sys.executable, "-u", "-c", bootstrap, root, *args]


def _run_command(command: list[str], result: Path, timeout: float) -> dict[str, Any]:
    """Bound a native/GIL stall by terminating and reaping our own interpreter."""
    from . import _proc
    options = _proc.new_session_kwargs()
    if sys.platform == "win32":
        options["creationflags"] = options.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    global _UNREAPED_PROCESS
    child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, **options)
    try:
        try:
            code = child.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            _proc.kill_process_tree(child, force=True, timeout=1.0)
            child.wait(timeout=2.0)
            raise
    finally:
        # Popen.__exit__ would wait without a deadline after a failed kill.
        # Retain the exact handle and refuse another probe until it exits.
        if child.poll() is None:
            _UNREAPED_PROCESS = child
    if code:
        raise RuntimeError("Hardware probe process failed")
    with result.open("rb") as stream:
        data = stream.read(MAX_RESULT_BYTES + 1)
    if len(data) > MAX_RESULT_BYTES:
        raise ValueError("Hardware probe result is too large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Invalid hardware probe result")
    return value


def query(operation: str, *, timeout: float = PROBE_TIMEOUT_S) -> dict[str, Any]:
    if operation not in ("cuda", "snapshot", "diagnostics"):
        raise ValueError("Unknown hardware probe operation")
    if not _PROBE_LOCK.acquire(blocking=False):
        raise RuntimeError("A hardware probe is already running")
    global _UNREAPED_PROCESS
    try:
        if _UNREAPED_PROCESS is not None:
            if _UNREAPED_PROCESS.poll() is None:
                raise RuntimeError("The previous hardware probe is still finishing")
            _UNREAPED_PROCESS = None
        with tempfile.TemporaryDirectory(prefix="wts-hardware-probe-") as directory:
            result = Path(directory) / "result.json"
            return _run_command(_command(operation, result), result, timeout)
    finally:
        _PROBE_LOCK.release()


def worker_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("cuda", "snapshot", "diagnostics"))
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    from dataclasses import asdict
    from . import hardware as hw
    from ._gc_import_guard import gc_disabled_import

    with gc_disabled_import():
        if args.operation == "diagnostics":
            value: dict[str, Any] = {"report": hw.diagnostics_report()}
        else:
            status = hw.cuda_status()
            value = {"cuda": asdict(status)}
            if args.operation == "snapshot":
                value["tiers"] = [asdict(tier) for tier in hw.probe_tiers(status)]
    # A windowed frozen interpreter may have no stdout; use an owned file.
    pending = args.result.with_suffix(".pending")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(args.result)


if __name__ == "__main__":
    worker_main()
