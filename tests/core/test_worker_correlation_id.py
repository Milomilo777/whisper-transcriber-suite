"""Task-correlation-id tests for ``core.worker``.

The bug being closed: the parent writes a ``transcribe`` command and a later
cancel/pause/resume for it from two different daemon threads through one
stdin pipe. If the control thread wins the lock the worker reads the control
BEFORE the transcribe it belongs to; with no in-flight task it used to be a
documented silent no-op, so the control was lost while the UI already showed
the task as paused/cancelled.

The fix is an optional ``task_id`` on both command kinds. These tests cover,
end to end through ``main()`` where possible:

- the exact bad ordering (control line first) now applies the control when
  the matching transcribe registers;
- a control for another task is never applied to the current one;
- an id-bearing control with no matching task is ACKNOWLEDGED as
  ``control_unmatched`` after a bounded wait, not silently swallowed;
- an id-less control keeps today's literal semantics (applies to current,
  silent no-op when none) — backward compatibility.

Hermetic: no subprocess, no model, no Tk, no network.
"""
from __future__ import annotations

import io
import json
import sys
import time
import types

import pytest

from core import worker


@pytest.fixture(autouse=True)
def _isolate_worker_state():
    """Never leak the current task or parked controls between tests."""
    worker._clear_parked_controls()
    worker._set_current_task(None)
    yield
    worker._clear_parked_controls()
    worker._set_current_task(None)


@pytest.fixture
def recorded(monkeypatch):
    """Capture every emit() as a dict instead of stdout (thread-safe)."""
    events: list[dict] = []

    def _record(event: str, **payload: object) -> None:
        events.append({"event": event, **payload})

    monkeypatch.setattr(worker, "emit", _record)
    return events


def _task(task_id: str = "", **flags: bool) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        cancelled=flags.get("cancelled", False),
        paused=flags.get("paused", False),
        task_id=task_id,
    )


def _run_main(monkeypatch, lines: list[dict], fake_transcribe) -> int:
    monkeypatch.setattr(worker, "load_existing_model", lambda cb: True)
    monkeypatch.setattr(worker, "transcribe", fake_transcribe)
    payload = "".join(json.dumps(line) + "\n" for line in lines)
    monkeypatch.setattr(sys, "stdin", io.StringIO(payload))
    return worker.main()


def _wait_for(
    events: list[dict],
    event: str,
    task_id: str | None = None,
    timeout: float = 5.0,
) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in list(events):
            if e.get("event") != event:
                continue
            if task_id is not None and e.get("task_id") != task_id:
                continue
            return e
        time.sleep(0.01)
    raise AssertionError(f"event {event!r} never arrived; got {events!r}")


# ---------------------------------------------------------------- routing units


def test_route_control_applies_immediately_to_the_matching_task(recorded):
    t = _task(task_id="h1")
    worker._set_current_task(t)

    worker._route_control("pause", "h1")

    assert t.paused is True
    assert recorded == [
        {"event": "control_applied", "action": "pause", "task_id": "h1",
         "delayed": False},
    ]


def test_route_control_for_another_task_is_parked_never_misapplied(recorded):
    t = _task(task_id="h1")
    worker._set_current_task(t)

    worker._route_control("cancel", "h2")

    assert t.cancelled is False
    assert recorded == []  # nothing applied, nothing acked yet
    assert list(worker._parked_controls) == ["h2"]


def test_route_control_never_matches_a_task_without_an_id(recorded):
    t = _task()  # legacy task: no task_id at all
    worker._set_current_task(t)

    worker._route_control("pause", "h1")

    assert t.paused is False
    assert list(worker._parked_controls) == ["h1"]


def test_int_and_str_task_ids_compare_equal(recorded):
    """The protocol promises an opaque token; both sides normalise it."""
    t = _task()
    t.task_id = 7  # a non-string id from some other client
    worker._set_current_task(t)

    worker._route_control("pause", "7")

    assert t.paused is True


def test_parked_controls_apply_in_arrival_order_at_registration(recorded):
    worker._route_control("pause", "h1")
    worker._route_control("resume", "h1")
    assert len(worker._parked_controls["h1"]) == 2

    task = _task(task_id="h1")
    parked = worker._register_task(task)

    assert [e.action for e in parked] == ["pause", "resume"]
    # pause then resume -> final state unpaused (wire order preserved).
    assert task.paused is False
    assert not worker._parked_controls


# ------------------------------------------- the original bad ordering, E2E


def test_pause_control_before_its_transcribe_is_honoured(monkeypatch, capsys):
    """THE regression: the pause line physically precedes the transcribe line
    (control thread won the stdin-lock race). The worker must park it by id
    and apply it when the transcribe registers — the task must start paused.
    """
    seen: list[tuple[str, bool, bool]] = []

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        seen.append((task.task_id, task.paused, task.cancelled))

    rc = _run_main(
        monkeypatch,
        [
            {"action": "pause", "task_id": "h1"},
            {"action": "transcribe", "file_path": "/tmp/x.wav", "task_id": "h1"},
            {"action": "shutdown"},
        ],
        fake_transcribe,
    )
    assert rc == 0
    assert seen == [("h1", True, False)]

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.strip().splitlines()
        if line.strip()
    ]
    applied = [e for e in events if e["event"] == "control_applied"]
    assert applied and applied[0]["delayed"] is True
    assert applied[0]["task_id"] == "h1"
    # Correlation id also rides the task's own events (add-only).
    assert next(e for e in events if e["event"] == "started")["task_id"] == "h1"
    assert next(e for e in events if e["event"] == "done")["task_id"] == "h1"


def test_cancel_control_before_its_transcribe_is_honoured(monkeypatch, capsys):
    """Same ordering with cancel: the task must observe cancelled=True at
    entry (the transcriber's between-segment poll then flushes a checkpoint
    and returns instead of transcribing the whole file)."""
    seen: list[tuple[str, bool]] = []

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        seen.append((task.task_id, task.cancelled))

    _run_main(
        monkeypatch,
        [
            {"action": "cancel", "task_id": "h2"},
            {"action": "transcribe", "file_path": "/tmp/y.wav", "task_id": "h2"},
            {"action": "shutdown"},
        ],
        fake_transcribe,
    )
    assert seen == [("h2", True)]
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.strip().splitlines()
        if line.strip()
    ]
    assert any(e["event"] == "done" for e in events)


def test_control_for_another_task_is_not_applied_to_the_next_task(
    monkeypatch, capsys
):
    """A cancel meant for task B arrives while task A is in flight (or while
    both are on the wire). It must be applied to B when B registers — never
    to A, and never dropped."""
    seen: list[tuple[str, bool]] = []

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        seen.append((task.task_id, task.cancelled))

    _run_main(
        monkeypatch,
        [
            {"action": "transcribe", "file_path": "/a.wav", "task_id": "hA"},
            {"action": "cancel", "task_id": "hB"},
            {"action": "transcribe", "file_path": "/b.wav", "task_id": "hB"},
            {"action": "shutdown"},
        ],
        fake_transcribe,
    )
    assert seen == [("hA", False), ("hB", True)]


def test_expire_helper_acks_and_removes_a_parked_control(monkeypatch, recorded):
    """Deterministic half of the timeout path (no timer scheduling needed):
    a parked entry past its deadline is removed and acked exactly once."""
    monkeypatch.setattr(worker, "CONTROL_PARK_TIMEOUT_S", 60.0)
    worker._route_control("cancel", "h404")
    entry = worker._parked_controls["h404"][0]
    entry.deadline = 0.0  # force expiry without waiting

    worker._expire_parked_controls()

    assert recorded == [
        {"event": "control_unmatched", "action": "cancel", "task_id": "h404",
         "reason": "timeout"},
    ]
    assert not worker._parked_controls
    assert not worker._parked_order
    # Calling it again must not double-ack.
    worker._expire_parked_controls()
    assert len(recorded) == 1


def test_unmatched_control_times_out_with_an_explicit_ack(monkeypatch, recorded):
    """No matching transcribe ever shows up -> one explicit control_unmatched
    after the bounded wait (the real park timer, not the helper), never a
    silent swallow."""
    monkeypatch.setattr(worker, "CONTROL_PARK_TIMEOUT_S", 0.0)

    worker._route_control("cancel", "h404")

    event = _wait_for(recorded, "control_unmatched", task_id="h404")
    assert event["action"] == "cancel"
    assert event["reason"] == "timeout"
    assert not worker._parked_controls


def test_idless_control_keeps_legacy_semantics(monkeypatch, recorded):
    """Backward compatibility: no id -> applies to the current task, and is a
    silent no-op (no event at all) when no task is in flight, exactly as the
    frozen protocol has always documented."""
    worker._route_control("pause", "")
    assert recorded == []
    assert not worker._parked_controls

    t = _task()  # legacy task, no id
    worker._set_current_task(t)
    worker._route_control("cancel", "")
    assert t.cancelled is True
    assert not worker._parked_controls
    assert recorded == []  # id-less controls are never acked


def test_idless_control_still_applies_to_an_id_bearing_task(monkeypatch, recorded):
    """An older parent's id-less control must keep working against a task
    that happens to carry an id (the parent simply doesn't know about ids)."""
    t = _task(task_id="h1")
    worker._set_current_task(t)

    worker._route_control("resume", "")

    assert t.paused is False
    assert not worker._parked_controls


def test_idless_control_before_transcribe_still_noops_exactly_as_before(
    monkeypatch, capsys
):
    """The retained legacy edge: an id-less control that overtakes its
    transcribe is STILL a silent no-op (the documented stray-control
    semantics; an old parent cannot be fixed worker-side). This is the
    backward-compatibility half of the fix — proving the new path did not
    change id-less behaviour at all."""
    seen: list[tuple[str, bool]] = []

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        seen.append((task.task_id, task.paused))

    _run_main(
        monkeypatch,
        [
            {"action": "pause"},  # no task_id — legacy stray control
            {"action": "transcribe", "file_path": "/tmp/z.wav"},
            {"action": "shutdown"},
        ],
        fake_transcribe,
    )
    assert seen == [("", False)]  # the pause was a no-op, exactly as before

    events = [
        json.loads(line)
        for line in capsys.readouterr().out.strip().splitlines()
        if line.strip()
    ]
    assert not any(e["event"] == "control_applied" for e in events)
    assert not any(e["event"] == "control_unmatched" for e in events)


def test_park_capacity_evicts_oldest_with_an_ack(monkeypatch, recorded):
    monkeypatch.setattr(worker, "_MAX_PARKED_CONTROLS", 2)
    worker._route_control("pause", "h1")
    worker._route_control("resume", "h1")
    worker._route_control("cancel", "h2")  # evicts the oldest (pause h1)

    evicted = [e for e in recorded if e["event"] == "control_unmatched"]
    assert [e["reason"] for e in evicted] == ["capacity"]
    assert evicted[0]["task_id"] == "h1"
    assert list(worker._parked_controls) == ["h1", "h2"]
    # The pair left for h1 is exactly [resume] — latest action preserved.
    assert [e.action for e in worker._parked_controls["h1"]] == ["resume"]


def test_park_timeout_does_not_ack_a_control_applied_at_registration(
    monkeypatch, recorded
):
    """The timer may fire after registration; it must find nothing to ack."""
    monkeypatch.setattr(worker, "CONTROL_PARK_TIMEOUT_S", 0.05)
    worker._route_control("pause", "h1")

    task = _task(task_id="h1")
    worker._register_task(task)
    time.sleep(0.15)

    assert [e for e in recorded if e["event"] == "control_unmatched"] == []
    assert task.paused is True


def test_register_task_publishes_current_for_legacy_transcribes(recorded):
    task = _task()
    parked = worker._register_task(task)
    assert parked == []
    assert worker._current_task is task
