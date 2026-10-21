"""Tests for the pure action-bar state helpers in ``app.widgets.tabs``.

R2 added always-visible per-task Pause/Resume/Cancel/Re-run/Remove controls
on the Queue and Download tabs. ``button_states_for_status`` (transcription)
and ``download_button_states_for_status`` (downloads) are the single source
of truth shared by each action bar AND its right-click context menu, so the
two can never drift. Both are pure functions — no Tk root needed.
"""
from __future__ import annotations

from app.widgets.tabs import (
    DOWNLOAD_ACTION_KEYS,
    QUEUE_ACTION_KEYS,
    button_states_for_status,
    download_button_states_for_status,
)


def _on(states: dict[str, bool]) -> set[str]:
    """The set of ENABLED action keys."""
    return {k for k, v in states.items() if v}


# --- button_states_for_status (transcription) ------------------------------


def test_states_keys_are_complete_and_default_false():
    # Every status returns exactly the documented key set, no extras.
    for status in ("waiting", "running", "paused", "finished", "cancelled",
                   "error", "weird-unknown"):
        states = button_states_for_status(status)
        assert set(states) == set(QUEUE_ACTION_KEYS)


def test_states_waiting_cancel_and_remove():
    # A job that has not started can leave the list (review, 2026-10-21).
    assert _on(button_states_for_status("waiting")) == {"cancel", "remove"}


def test_states_running_pause_and_cancel():
    # Mirrors menu_row: running -> Pause + Cancel.
    assert _on(button_states_for_status("running")) == {"pause", "cancel"}


def test_states_paused_resume_and_cancel():
    assert _on(button_states_for_status("paused")) == {"resume", "cancel"}


def test_states_finished_rerun_and_remove():
    # menu_row offers Re-run + Remove (plus finished-only extras handled
    # separately); no Resume for finished even with a checkpoint flag.
    assert _on(button_states_for_status("finished")) == {"rerun", "remove"}
    assert _on(button_states_for_status("finished", has_checkpoint=True)) == {
        "rerun", "remove"
    }


def test_states_error_rerun_and_remove_no_resume():
    assert _on(button_states_for_status("error")) == {"rerun", "remove"}
    # Error never invites a resume from a possibly-stale partial.
    assert _on(button_states_for_status("error", has_checkpoint=True)) == {
        "rerun", "remove"
    }


def test_states_cancelled_without_checkpoint():
    assert _on(button_states_for_status("cancelled")) == {"rerun", "remove"}


def test_states_cancelled_never_offers_resume():
    # Resume next to Re-run on a cancelled job asked users to tell two restarts apart (deep
    # review, 2026-10-21): only Re-run is offered, with or without a checkpoint.
    assert _on(button_states_for_status("cancelled", has_checkpoint=True)) == {"rerun", "remove"}


def test_states_unknown_status_disables_everything():
    assert _on(button_states_for_status("")) == set()
    assert _on(button_states_for_status("transcribing")) == set()


# --- download_button_states_for_status -------------------------------------


def test_download_states_keys_complete():
    for status in ("waiting", "running", "paused", "finished", "cancelled",
                   "error", "transcribing", "huh"):
        states = download_button_states_for_status(status)
        assert set(states) == set(DOWNLOAD_ACTION_KEYS)


def test_download_running_offers_pause_and_cancel():
    # A running non-SMTV download can stop-and-continue (Pause).
    assert _on(download_button_states_for_status("running")) == {"pause", "cancel"}


def test_download_running_smtv_disables_pause():
    # SMTV CDN has no HTTP Range resume point, so Pause is unavailable.
    assert _on(download_button_states_for_status("running", is_smtv=True)) == {
        "cancel"
    }


def test_download_waiting_and_transcribing_only_cancel():
    assert _on(download_button_states_for_status("waiting")) == {"cancel"}
    assert _on(download_button_states_for_status("transcribing")) == {"cancel"}


def test_download_paused_offers_resume_and_cancel():
    assert _on(download_button_states_for_status("paused")) == {"resume", "cancel"}


def test_download_terminal_rerun_remove():
    assert _on(download_button_states_for_status("cancelled")) == {"rerun", "remove"}
    assert _on(download_button_states_for_status("error")) == {"rerun", "remove"}


def test_download_finished_open_only_with_saved_file():
    # Open appears only when a finished download actually has a file on disk.
    assert _on(download_button_states_for_status("finished")) == {"rerun", "remove"}
    assert _on(
        download_button_states_for_status("finished", has_saved_file=True)
    ) == {"rerun", "remove", "open"}


def test_download_open_not_offered_for_non_finished():
    # A cancelled/error row never offers Open even if it somehow has a path.
    assert "open" not in _on(
        download_button_states_for_status("cancelled", has_saved_file=True)
    )
