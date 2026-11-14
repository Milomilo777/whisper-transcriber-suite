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
        try:
            process = psutil.Process(identity["pid"])
            if (not process.is_running() or process.create_time() != identity["created"]
                    or os.path.realpath(process.exe()) != target):
                continue  # The original exited; a reused PID is never ours.
            process.terminate()  # psutil also checks PID reuse before signalling.
            process.wait(timeout=3)
        except psutil.NoSuchProcess:
            continue
        except (psutil.AccessDenied, psutil.TimeoutExpired):
            complete = False
    # A new bootloader child is not authorised by the old receipt. Do not kill
    # it, but do not claim cleanup or remove its copy while it remains alive.
    remaining = owned_processes(target, started, include_older=True)
    return complete and not remaining


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
