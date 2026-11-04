"""Hermetic tests for implicit __context__ chaining in core.failure_clue.worker_clue."""
from __future__ import annotations

import errno

from core import failure_clue


def test_worker_clue_follows_unsuppressed_context_in_model_site() -> None:
    try:
        try:
            raise OSError(errno.ENOSPC, "No space left on device", "C:\\Users\\टेस्ट\\model.bin")
        except OSError:
            raise RuntimeError("Model load wrapper failed")
    except RuntimeError as exc:
        clue = failure_clue.worker_clue(exc, site="worker.model", device="cpu")

    assert clue["failure_site"] == "worker.model"
    assert clue["exception_family"] == "OSError", f"Expected OSError from __context__, got {clue['exception_family']!r}"
    assert clue["observed_code"] == "disk_full"
    assert clue["os_error"] == str(errno.ENOSPC)


def test_worker_clue_follows_unsuppressed_context_in_prepare_site() -> None:
    try:
        try:
            raise PermissionError(errno.EACCES, "Permission denied", "/tmp/नॉन_एएससीआईआई/audio.wav")
        except PermissionError:
            raise ValueError("Prepare step failed")
    except ValueError as exc:
        clue = failure_clue.worker_clue(exc, site="worker.prepare", device="cpu")

    assert clue["failure_site"] == "worker.prepare"
    assert clue["exception_family"] == "PermissionError"
    assert clue["observed_code"] == "access_denied"
    assert clue["os_error"] == str(errno.EACCES)


def test_worker_clue_respects_suppressed_context_from_none() -> None:
    try:
        try:
            raise OSError(errno.ENOSPC, "No space left on device")
        except OSError:
            raise RuntimeError("Deliberately replaced error") from None
    except RuntimeError as exc:
        clue = failure_clue.worker_clue(exc, site="worker.model", device="cpu")

    assert clue["failure_site"] == "worker.model"
    assert clue["exception_family"] == "RuntimeError"
    assert clue["observed_code"] == "none"
    assert clue["os_error"] == "0"


def test_worker_clue_handles_cyclic_context_chain_without_infinite_loop() -> None:
    first = OSError(errno.ENOSPC, "Disk full")
    second = RuntimeError("Outer wrapper")
    second.__context__ = first
    first.__context__ = second

    clue = failure_clue.worker_clue(second, site="worker.model", device="cpu")
    assert clue["failure_site"] == "worker.model"
    assert clue["exception_family"] == "OSError"
    assert clue["observed_code"] == "disk_full"


def test_worker_clue_does_not_unwrap_context_on_non_model_prepare_sites() -> None:
    try:
        try:
            raise KeyError("inner")
        except KeyError:
            raise ValueError("outer segments error")
    except ValueError as exc:
        clue = failure_clue.worker_clue(exc, site="worker.segments", device="cpu")

    assert clue["failure_site"] == "worker.segments"
    assert clue["exception_family"] == "ValueError"
