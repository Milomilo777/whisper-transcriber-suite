"""reserve_output_path races (defect hunt): a failed exclusive create must
never release the reservation another job just won, and a pre-existing
user file must not stay reserved forever. Hermetic: tmp_path only.
"""
from __future__ import annotations

import os

from core import burn_subs as burn


def test_failed_create_keeps_the_reservation_the_winner_won(monkeypatch, tmp_path):
    """Two jobs race for the same output name. Job B wins the exclusive
    create between job A's set-add and A's open; A's cleanup used to
    discard the key B now owns, so the watched folder saw B's empty
    placeholder as user input and enqueued a 0-byte video."""
    target = tmp_path / "out.mp4"
    real_open = burn.os.open
    state = {"nested_done": False}

    def _open(path, flags, *a, **k):
        if (not state["nested_done"]
                and burn._output_key(str(path)) == burn._output_key(str(target))):
            state["nested_done"] = True
            # Job B's whole reservation happens inside A's open call.
            won = burn.reserve_output_path(str(target))
            assert won == str(target)
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(burn.os, "open", _open)
    got = burn.reserve_output_path(str(target))
    assert got != str(target)  # A moved on to "out (2).mp4"
    # B's placeholder stays reserved.
    assert burn.is_reserved(str(target)) is True
    # A's own placeholder is reserved too.
    assert burn.is_reserved(got) is True


def test_a_pre_existing_user_file_is_not_left_reserved(tmp_path):
    """A file the user put there is not a placeholder: the failed
    reservation must release the key, or the watcher would ignore that
    real file forever."""
    target = tmp_path / "out.mp4"
    target.write_bytes(b"user data")
    got = burn.reserve_output_path(str(target))
    assert got == str(tmp_path / "out (2).mp4")
    assert burn.is_reserved(str(target)) is False
    assert burn.is_reserved(got) is True


def test_loser_cleanup_cannot_unreserve_a_placeholder_created_but_not_yet_returned(
        monkeypatch, tmp_path):
    """Coordinated two-thread interleaving: job A has listed the name and is
    paused right before its exclusive create; job B lists the name, creates
    the placeholder and is paused right after the create; only then A runs
    its failed create and cleanup. B's placeholder must stay reserved, or the
    watched folder takes the empty file for user input."""
    import threading

    target = tmp_path / "out.mp4"
    real_open = burn.os.open
    a_before_open = threading.Event()
    a_go = threading.Event()
    b_created = threading.Event()
    b_go = threading.Event()
    seen = {"b_path": None, "a_paused": False, "b_paused": False}

    def _open(path, flags, *a, **k):
        name = threading.current_thread().name
        if name == "job-A" and not seen["a_paused"]:
            seen["a_paused"] = True
            a_before_open.set()
            assert a_go.wait(10)
        fd = real_open(path, flags, *a, **k)
        if name == "job-B" and not seen["b_paused"]:
            seen["b_paused"] = True
            seen["b_path"] = str(path)
            b_created.set()
            assert b_go.wait(10)
        return fd

    monkeypatch.setattr(burn.os, "open", _open)
    results: dict[str, str] = {}

    def _job(label):
        results[label] = burn.reserve_output_path(str(target))

    ta = threading.Thread(target=_job, args=("A",), name="job-A")
    tb = threading.Thread(target=_job, args=("B",), name="job-B")
    ta.start()
    assert a_before_open.wait(10)
    tb.start()
    # With the fix B may be held back until A has finished; either way the
    # check below runs at the moment B has created its placeholder.
    b_created.wait(1.0)
    a_go.set()
    if not b_created.is_set():
        ta.join(10)
        assert b_created.wait(10)
    else:
        ta.join(10)
    try:
        assert not ta.is_alive()
        assert seen["b_path"] is not None
        assert burn.is_reserved(seen["b_path"]) is True
    finally:
        b_go.set()
        tb.join(10)
    assert results["A"] != results["B"]
    assert burn.is_reserved(results["A"]) and burn.is_reserved(results["B"])
