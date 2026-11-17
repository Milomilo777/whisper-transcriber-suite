"""Identify only this copied app; never infer ownership from command arguments."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import sys

psutil = None


def process_api():
    global psutil
    if psutil is None:
        import psutil as native_psutil
        psutil = native_psutil
    return psutil


def owned_processes(executable: str, started: float, *, include_older: bool = False) -> list[dict]:
    process_api()
    if not math.isfinite(started) or started <= 0:
        raise ValueError("Invalid launch timestamp")
    target = os.path.realpath(executable)
    identities = []
    for index, process in enumerate(psutil.process_iter()):
        if index >= 4096:
            raise ValueError("Process enumeration limit exceeded")
        matched = False
        try:
            created = process.create_time()
            matched = (math.isfinite(created) and (include_older or created >= started)
                       and os.path.realpath(process.exe()) == target)
            if matched and process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                identities.append({"pid": process.pid, "created": created})
                if len(identities) > 64:
                    raise ValueError("Too many copied app processes")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            if matched:
                raise RuntimeError("Owned process state unavailable") from None
    return identities


def capture(executable: str, started: float, receipt: Path) -> bool:
    target = os.path.realpath(executable)
    identities = owned_processes(target, started)
    payload = {"executable": target, "started": started, "processes": identities}
    temporary = receipt.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload), encoding="utf-8")
    temporary.replace(receipt)
    print(json.dumps({"owned_processes": identities}))
    return bool(identities)


def cleanup_diagnostic(phase: str, *, identity=None, error=None,
                       outcome=None, remaining=None) -> None:
    """Emit only phase/type and validated identities, never exception text."""
    payload = {"phase": phase}
    if error is not None:
        payload["error_type"] = type(error).__name__
    if identity is not None:
        payload["identity"] = {key: identity[key] for key in ("pid", "created")}
    if outcome is not None:
        payload["outcome"] = outcome
    if remaining is not None:
        payload["remaining"] = [{key: row[key] for key in ("pid", "created")}
                                for row in remaining]
    message = json.dumps({"copied_gui_cleanup": payload})
    try:
        print(message, file=sys.stderr)
    except (OSError, ValueError):
        # A broken/closed diagnostic sink must not change cleanup's result.
        pass


def stop(executable: str, started: float, receipt: Path) -> bool:
    process_api()
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    target = os.path.realpath(executable)
    if payload["executable"] != target or payload["started"] != started:
        raise ValueError("Launch receipt does not match this copy")
    entries = payload["processes"]
    # Validate the entire receipt before signalling any process.
    if (not isinstance(entries, list) or len(entries) > 64
            or any(not isinstance(row, dict) or type(row.get("pid")) is not int
                   or row["pid"] <= 1 or type(row.get("created")) not in (int, float)
                   or not math.isfinite(row["created"]) or row["created"] < started
                   for row in entries)):
        raise ValueError("Invalid process identities")
    complete = True
    for identity in entries:
        phase = "lookup"
        try:
            process = psutil.Process(identity["pid"])
            phase = "identity"
            if (not process.is_running() or process.create_time() != identity["created"]
                    or os.path.realpath(process.exe()) != target):
                continue  # The original exited; a reused PID is never ours.
            phase = "terminate"
            process.terminate()  # psutil also checks PID reuse before signalling.
            phase = "wait"
            process.wait(timeout=3)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.TimeoutExpired) as error:
            cleanup_diagnostic(phase, identity=identity, error=error)
            complete = False
        except Exception as error:
            cleanup_diagnostic(phase, identity=identity, error=error)
            raise
    # A new bootloader child is not authorised by the old receipt. Do not kill
    # it, but do not claim cleanup or remove its copy while it remains alive.
    try:
        remaining = owned_processes(target, started, include_older=True)
    except Exception as error:
        cleanup_diagnostic("remaining_scan", error=error)
        raise
    resolved = complete and not remaining
    cleanup_diagnostic("complete", outcome="resolved" if resolved else "unresolved",
                       remaining=remaining)
    return resolved


def main() -> int:
    try:
        if sys.argv[1:] == ["preflight"]:
            process_api()
            return 0
        if len(sys.argv) != 5 or sys.argv[1] not in ("capture", "stop"):
            return 2
        process_api()
        action, executable, started_text, receipt_text = sys.argv[1:]
        started = float(started_text)
        if not math.isfinite(started) or started <= 0:
            raise ValueError("Invalid launch timestamp")
        method = capture if action == "capture" else stop
        return 0 if method(executable, started, Path(receipt_text)) else 1
    except Exception as error:
        print("Copied GUI process proof unavailable: " + type(error).__name__, file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
