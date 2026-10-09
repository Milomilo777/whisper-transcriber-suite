"""Pure helpers of ``core.worker`` for control commands and task ids.

A control command sets one flag on a task; an unknown action must change
nothing and say so. Task ids are opaque tokens: whatever scalar a client
sends has to compare equal on the transcribe side and the control side.
Hermetic: plain namespaces, no worker process.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from core import worker


def _task() -> SimpleNamespace:
    return SimpleNamespace(cancelled=False, paused=False)


def test_cancel_sets_the_cancelled_flag_only():
    task = _task()
    assert worker._apply_control_flag(task, "cancel") is True  # type: ignore[arg-type]
    assert (task.cancelled, task.paused) == (True, False)


def test_pause_and_resume_toggle_the_paused_flag():
    task = _task()
    assert worker._apply_control_flag(task, "pause") is True  # type: ignore[arg-type]
    assert task.paused is True
    assert worker._apply_control_flag(task, "resume") is True  # type: ignore[arg-type]
    assert task.paused is False
    assert task.cancelled is False


@pytest.mark.parametrize("action", ["self_destruct", "", "CANCEL", "Pause", " cancel"])
def test_an_unknown_action_changes_nothing(action):
    task = _task()
    assert worker._apply_control_flag(task, action) is False  # type: ignore[arg-type]
    assert (task.cancelled, task.paused) == (False, False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, ""),
        ("", ""),
        ("  h12  ", "h12"),
        (123, "123"),
        (0, "0"),
        ("\u0634\u0646\u0627\u0633\u0647", "\u0634\u0646\u0627\u0633\u0647"),
    ],
)
def test_task_ids_are_normalised_to_a_stripped_string(value, expected):
    assert worker._normalise_task_id(value) == expected


def test_a_number_and_its_text_form_name_the_same_task():
    assert worker._normalise_task_id(42) == worker._normalise_task_id(" 42 ")
