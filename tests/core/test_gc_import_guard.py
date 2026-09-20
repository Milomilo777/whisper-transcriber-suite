"""Tests for the shared core._gc_import_guard.

Regression coverage for a real bug found in a second-pass code review of
the 2026-08-15 GC-hardening commit: the first version of this mitigation
gave every guarded call site its OWN threading.Lock(), which does not
actually serialize gc.disable()/gc.enable() (a PROCESS-GLOBAL pair)
across modules. Two differently-locked probes running concurrently could
still race and re-enable GC mid-import on the other thread -- exactly
the crash class this mitigation exists to prevent. See
docs/history/CODE_REVIEW_v1.7.0_2026-08-15.md.
"""
from __future__ import annotations

import gc
import threading

import pytest

from core._gc_import_guard import gc_disabled_import


def test_gc_disabled_import_restores_prior_state():
    for was_enabled in (True, False):
        if was_enabled:
            gc.enable()
        else:
            gc.disable()
        try:
            with gc_disabled_import():
                assert gc.isenabled() is False
            assert gc.isenabled() is was_enabled
        finally:
            gc.enable()


def test_gc_disabled_import_restores_state_when_the_body_raises():
    """Exception safety: a heavy import that blows up must still leave
    process-wide GC exactly as it found it."""
    gc.enable()
    with pytest.raises(RuntimeError, match="boom"):
        with gc_disabled_import():
            assert gc.isenabled() is False
            raise RuntimeError("boom")
    assert gc.isenabled() is True


def test_gc_disabled_import_keeps_gc_off_if_it_was_off_when_the_body_raises():
    gc.disable()
    try:
        with pytest.raises(RuntimeError, match="boom"):
            with gc_disabled_import():
                raise RuntimeError("boom")
        assert gc.isenabled() is False
    finally:
        gc.enable()


def test_gc_disabled_import_releases_the_guard_when_the_body_raises():
    """The lock must be released on the exception path, or the very next
    guarded import anywhere in the process deadlocks forever.

    The re-entry runs on a thread with a join timeout so a regression
    fails the test instead of hanging the whole suite.
    """
    gc.enable()
    with pytest.raises(RuntimeError, match="boom"):
        with gc_disabled_import():
            raise RuntimeError("boom")

    entered = threading.Event()

    def second() -> None:
        with gc_disabled_import():
            entered.set()

    t = threading.Thread(target=second, daemon=True)
    t.start()
    t.join(timeout=2.0)
    assert entered.is_set(), "guard lock was not released after the body raised"
    assert not t.is_alive()
    assert gc.isenabled() is True


def test_gc_disabled_import_serializes_across_two_different_callers():
    """The bug this regression-tests: two guarded blocks entered from
    different call sites must share ONE lock, not race each other.

    Holds the guard open on the main thread (simulating one probe's
    heavy import in progress), then starts a second thread that also
    enters the SAME guard (simulating an unrelated probe, e.g. a
    different backend's availability check). The second caller must
    block until the first exits -- if each had its own lock (the
    original bug), the second thread would sail through immediately
    and could re-enable GC while the first is still "importing".
    """
    entered = threading.Event()
    release = threading.Event()
    second_entered = threading.Event()

    def first():
        with gc_disabled_import():
            entered.set()
            release.wait(timeout=5.0)

    t1 = threading.Thread(target=first, daemon=True)
    t1.start()
    assert entered.wait(timeout=2.0), "first caller never entered the guard"

    def second():
        with gc_disabled_import():
            second_entered.set()

    t2 = threading.Thread(target=second, daemon=True)
    t2.start()
    # The second caller must NOT be able to enter while the first still
    # holds the guard -- give it a real chance to (wrongly) race through.
    assert not second_entered.wait(timeout=0.3), (
        "a second guarded caller entered while the first still held the "
        "guard -- the lock is not actually shared"
    )

    release.set()
    t1.join(timeout=3.0)
    assert second_entered.wait(timeout=3.0), (
        "second caller never got in after the first released the guard"
    )
    t2.join(timeout=3.0)
    assert gc.isenabled(), "GC must end up enabled after both guards exit"
