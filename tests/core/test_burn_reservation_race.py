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
