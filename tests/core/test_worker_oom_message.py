"""An out-of-memory job failure reaches the app as a plain explanation."""
from __future__ import annotations

import pytest

from core import worker


@pytest.mark.parametrize("exc", [
    MemoryError("Unable to allocate 2.15 GiB for an array with shape (1, 1440000, 400)"),
    MemoryError(),
    RuntimeError("std::bad_alloc"),
    RuntimeError("CUDA failed with error out of memory"),
])
def test_out_of_memory_errors_get_the_note(exc):
    message = worker._job_error_message(exc)
    assert message.startswith(worker.OUT_OF_MEMORY_NOTE)
    assert type(exc).__name__ in message
    assert str(exc) in message  # the original detail is kept for support


@pytest.mark.parametrize("exc", [
    RuntimeError("Invalid data found when processing input"),
    ValueError("Time range start (900s) is at or beyond the media length"),
])
def test_other_errors_are_unchanged(exc):
    assert worker._job_error_message(exc) == str(exc)
