"""Disposable process boundary for UI hardware checks and engine readiness."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
from typing import Any, Callable

_PROBE_LOCK = threading.Lock()
_ENGINE_PROBE_LOCK = threading.Lock()
_UNREAPED_PROCESS: subprocess.Popen[Any] | None = None
_UNREAPED_ENGINE_PROCESS: subprocess.Popen[Any] | None = None
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


def _run_command(
    command: list[str], result: Path, timeout: float, *, engine: bool = False,
) -> dict[str, Any]:
    """Bound a native/GIL stall by terminating and reaping our own interpreter."""
    from . import _proc
    options = _proc.new_session_kwargs()
    if sys.platform == "win32":
        options["creationflags"] = options.get("creationflags", 0) | subprocess.CREATE_NO_WINDOW
    global _UNREAPED_PROCESS, _UNREAPED_ENGINE_PROCESS
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
            if engine:
                _UNREAPED_ENGINE_PROCESS = child
            else:
                _UNREAPED_PROCESS = child
    if code:
        raise RuntimeError(f"Hardware probe process failed (exit {code})")
    with result.open("rb") as stream:
        data = stream.read(MAX_RESULT_BYTES + 1)
    if len(data) > MAX_RESULT_BYTES:
        raise ValueError("Hardware probe result is too large")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError("Invalid hardware probe result")
    if value.get("error"):
        raise RuntimeError(str(value["error"]))
    return value


def query(
    operation: str, *, timeout: float = PROBE_TIMEOUT_S, request: dict[str, Any] | None = None,
    current: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    if operation not in ("cuda", "snapshot", "diagnostics", "engine"):
        raise ValueError("Unknown hardware probe operation")
    engine = operation == "engine"
    lock = _ENGINE_PROBE_LOCK if engine else _PROBE_LOCK
    # Only background threads queue engine work. Skip superseded selections
    # before starting a child so a burst cannot crowd out the latest probe.
    if not lock.acquire(blocking=engine):
        raise RuntimeError("A hardware probe is already running")
    global _UNREAPED_ENGINE_PROCESS, _UNREAPED_PROCESS
    try:
        if current is not None and not current():
            raise RuntimeError("The engine selection changed")
        previous = _UNREAPED_ENGINE_PROCESS if engine else _UNREAPED_PROCESS
        if previous is not None and previous.poll() is None:
            raise RuntimeError("The previous hardware probe is still finishing")
        if engine:
            _UNREAPED_ENGINE_PROCESS = None
        else:
            _UNREAPED_PROCESS = None
        with tempfile.TemporaryDirectory(prefix="wts-hardware-probe-") as directory:
            result = Path(directory) / "result.json"
            if request is not None:
                result.with_name("request.json").write_text(json.dumps(request), encoding="utf-8")
            return _run_command(_command(operation, result), result, timeout, engine=engine)
    finally:
        lock.release()


NATIVE_COMPONENT_MODULES = (
    "numpy.core._multiarray_umath", "ctranslate2._ext",
    "av._core", "onnxruntime.capi.onnxruntime_pybind11_state", "PIL._imaging",
    "bidi.bidi", "google._upb._message", "sherpa_onnx.lib._sherpa_onnx", "hf_xet.hf_xet",
)


def _native_component_report() -> dict[str, Any]:
    import importlib
    for name in NATIVE_COMPONENT_MODULES:
        try:
            importlib.import_module(name)
        except Exception as error:
            raise RuntimeError("Required native component failed: " + name) from error
    return {"native_components": list(NATIVE_COMPONENT_MODULES)}


def worker_main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("cuda", "snapshot", "diagnostics", "native-components", "engine"))
    parser.add_argument("result", type=Path)
    args = parser.parse_args()
    from dataclasses import asdict
    from ._gc_import_guard import gc_disabled_import

    try:
        with gc_disabled_import():
            if args.operation == "native-components":
                value: dict[str, Any] = _native_component_report()
            elif args.operation == "engine":
                from . import optional_deps
                from .backends.availability import engine_status

                optional_deps.activate()
                request = json.loads(args.result.with_name("request.json").read_text(encoding="utf-8"))
                value = asdict(engine_status(request["engine"], request["config"], deep=True))
            else:
                from . import hardware as hw

                if args.operation == "diagnostics":
                    value = {"report": hw.diagnostics_report()}
                else:
                    status = hw.cuda_status()
                    value = {"cuda": asdict(status)}
                    if args.operation == "snapshot":
                        value["tiers"] = [asdict(tier) for tier in hw.probe_tiers(status)]
    except Exception as error:
        # Windowed PyInstaller reports an unhandled Python exception in a
        # dialog. Keep expected probe failures in the file protocol instead.
        value = {"error": str(error), "error_type": type(error).__name__}
    # A windowed frozen interpreter may have no stdout; use an owned file.
    pending = args.result.with_suffix(".pending")
    with pending.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    pending.replace(args.result)


if __name__ == "__main__":
    worker_main()
