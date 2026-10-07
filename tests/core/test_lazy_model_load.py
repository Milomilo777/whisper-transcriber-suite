"""Tests for v1.0.3 lazy Whisper-model loading.

Historically the App spawned a "standby" worker subprocess at launch
so the first transcribe was instant. v1.0.3 defers that work until
the user actually clicks Transcribe (or the watched-folder /
crash-resume paths fire). These tests cover:

  1. ``App._on_start`` does NOT call ``start_standby`` any more.
  2. ``ensure_worker_ready`` short-circuits True when a ready
     worker already exists.
  3. ``ensure_worker_ready`` spawns a worker when none is alive.
  4. The Cancel path returns False and tears the worker back down.

The tests use a hand-rolled FakeApp instead of a real ``tk.Tk()``
because (a) the unit suite runs headless on CI machines that have
no display, and (b) we don't want to load the actual Whisper model.
"""
from __future__ import annotations

import threading
import types
from typing import Any
from unittest.mock import MagicMock, patch

from app.services.transcription_service import TranscriptionService


# ---------------------------------------------------------------------------
# FakeApp — minimum surface area for TranscriptionService.
# ---------------------------------------------------------------------------


class _FakeStringVar:
    def __init__(self, value: str = "") -> None:
        self._v = value

    def set(self, v: str) -> None:
        self._v = v

    def get(self) -> str:
        return self._v


class _FakeApp:
    """Stand-in for ``app.app.App`` with just enough surface to run
    the lazy-load + worker-lifecycle service methods.

    No Tk root, no real subprocess. ``start_worker`` is patched at
    the service-instance level in the test that needs spawn
    verification.
    """

    def __init__(self) -> None:
        self.workers: list[dict[str, Any]] = []
        self.next_worker_id = 1
        # Plain list since we never push real events in these tests.
        self.worker_events: list[Any] = []
        self.status_var = _FakeStringVar("idle")
        self.model_ready = False
        self.model_loading = False
        self.worker_ready = False
        self.parallel_workers = 2
        self.queue: list[Any] = []
        # The service routes dialog destroys through post_to_main;
        # in tests we just run them inline.
        self.main_thread_calls: list[Any] = []
        self.entry_file = __file__
        self.app_config: dict[str, Any] = {"model": {"name": "tiny"}}
        # Tasks frame-of-reference for the dispatcher (unused here).
        self.history = None

    def after(self, *_a: Any, **_k: Any) -> None:
        # The service schedules its poll loop via app.after — no-op
        # in tests because we never want a Tk loop running.
        return None

    def post_to_main(self, fn: Any) -> None:
        # Run inline so tests can observe the dialog being closed.
        fn()

    def update_overall_progress(self) -> None:
        pass

    def log(self, _msg: str) -> None:
        pass


# ---------------------------------------------------------------------------
# Test 1: _on_start no longer preloads the worker.
# ---------------------------------------------------------------------------


def test_on_start_does_not_call_start_standby(monkeypatch: Any) -> None:
    """v1.0.3 removed the preload. ``App._on_start`` must NOT call
    ``TranscriptionService.start_standby`` regardless of whether
    the hub is already configured.
    """
    from app import app as app_module

    # Spy that records every call to start_standby.
    calls: list[bool] = []

    def _spy_standby(self: TranscriptionService) -> None:
        calls.append(True)

    monkeypatch.setattr(
        TranscriptionService, "start_standby", _spy_standby,
    )

    # Make hub appear configured so _on_start takes the early-return
    # branch without trying to construct the hub-setup dialog.
    monkeypatch.setattr(
        "core.hub.is_hub_configured", lambda _cfg: True,
    )

    # Build a fake "self" with just the attributes _on_start touches.
    fake_self = types.SimpleNamespace(
        app_config={},
        transcription_service=TranscriptionService(_FakeApp()),  # type: ignore[arg-type]
        log=lambda _m: None,
        # _on_start hands the model-folder check to this App method.
        _ensure_hub_folder=lambda: app_module.App._ensure_hub_folder(fake_self),  # type: ignore[arg-type]
    )

    app_module.App._on_start(fake_self)  # type: ignore[arg-type]

    assert calls == [], (
        f"_on_start must not preload via start_standby; got {len(calls)} calls"
    )


def test_on_start_does_not_call_start_standby_when_hub_unset(monkeypatch: Any) -> None:
    """Even when the hub-setup dialog needs to fire, _on_start must
    not preload — the worker only spawns when the user clicks
    Transcribe.
    """
    from app import app as app_module

    calls: list[bool] = []
    monkeypatch.setattr(
        TranscriptionService, "start_standby",
        lambda self: calls.append(True),
    )
    monkeypatch.setattr(
        "core.hub.is_hub_configured", lambda _cfg: False,
    )

    # Patch the hub-setup dialog opener so the test doesn't try to
    # build a real Tk Toplevel.
    monkeypatch.setattr(
        "app.dialogs.hub_setup.ensure_hub_configured",
        lambda *_a, **_k: None,
    )

    fake_self = types.SimpleNamespace(
        app_config={},
        transcription_service=TranscriptionService(_FakeApp()),  # type: ignore[arg-type]
        log=lambda _m: None,
        # _on_start hands the model-folder check to this App method.
        _ensure_hub_folder=lambda: app_module.App._ensure_hub_folder(fake_self),  # type: ignore[arg-type]
    )
    app_module.App._on_start(fake_self)  # type: ignore[arg-type]

    assert calls == []


# ---------------------------------------------------------------------------
# Test 2: ensure_worker_ready short-circuits when ready worker present.
# ---------------------------------------------------------------------------


def test_ensure_worker_ready_returns_true_when_ready_worker_exists() -> None:
    app = _FakeApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]

    # Fake a worker that's alive + ready.
    fake_process = MagicMock()
    fake_process.poll.return_value = None  # alive
    app.workers.append({
        "id": 1, "process": fake_process, "ready": True,
        "task": None, "temporary": False, "token": "abc",
        "last_event_at": 0.0,
    })

    # If the fast-path works, start_worker must NOT be called.
    with patch.object(svc, "start_worker") as mock_spawn:
        result = svc.ensure_worker_ready(MagicMock())  # parent unused

    assert result is True
    mock_spawn.assert_not_called()


# ---------------------------------------------------------------------------
# Test 3: ensure_worker_ready spawns a worker when none alive.
# ---------------------------------------------------------------------------


def test_ensure_worker_ready_spawns_when_no_worker_alive_headless() -> None:
    """No alive workers → start_worker called. We use the headless
    path so the test doesn't need a Tk root for the modal."""
    app = _FakeApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]

    def fake_start_worker(worker: Any = None, temporary: bool = False) -> None:
        # Mimic start_worker's bookkeeping enough for ensure_worker_ready
        # to discover the new id and bind a pending_load record.
        new = {
            "id": app.next_worker_id, "process": MagicMock(poll=lambda: None),
            "ready": False, "task": None, "temporary": temporary,
            "token": "tkn", "last_event_at": 0.0,
        }
        app.next_worker_id += 1
        app.workers.append(new)

    with patch.object(svc, "start_worker", side_effect=fake_start_worker) as mock_spawn:
        # Run ensure_worker_ready on a background thread so the main
        # thread can simulate the ready event landing.
        result_holder: list[bool] = []

        def _runner() -> None:
            result_holder.append(svc.ensure_worker_ready(MagicMock(), headless=True))

        t = threading.Thread(target=_runner, daemon=True)
        t.start()

        # Wait for the spawn + pending_load_event to be set up.
        for _ in range(200):  # up to 2 s
            if svc._pending_load_event is not None:
                break
            import time as _t
            _t.sleep(0.01)

        assert svc._pending_load_event is not None, (
            "ensure_worker_ready never set _pending_load_event — did "
            "start_worker fail to register a new worker id?"
        )

        # Simulate the ready event landing on the awaited worker: poll()
        # marks it ready, then releases the waiter.
        app.workers[-1]["ready"] = True
        svc._pending_load_event.set()
        t.join(timeout=5.0)

    mock_spawn.assert_called_once()
    assert result_holder == [True]


# ---------------------------------------------------------------------------
# Test 4: Cancel path → False + worker retired.
# ---------------------------------------------------------------------------


def test_cancel_path_returns_false_and_retires_worker() -> None:
    """Simulate the user clicking Cancel on the modal: success
    stays False and the just-spawned worker is torn down."""
    app = _FakeApp()
    svc = TranscriptionService(app)  # type: ignore[arg-type]

    spawned: list[dict[str, Any]] = []

    def fake_start_worker(worker: Any = None, temporary: bool = False) -> None:
        proc = MagicMock()
        proc.poll.return_value = None
        new = {
            "id": app.next_worker_id, "process": proc, "ready": False,
            "task": None, "temporary": temporary, "token": "x",
            "last_event_at": 0.0,
        }
        app.next_worker_id += 1
        app.workers.append(new)
        spawned.append(new)

    retired: list[dict[str, Any]] = []
    monkey_retire_target = svc.retire_worker

    def fake_retire(worker: dict[str, Any]) -> None:
        retired.append(worker)
        if worker in app.workers:
            app.workers.remove(worker)

    # Patch the dialog so wait_window returns immediately with
    # success=False (the Cancel result).
    fake_dialog_cls = MagicMock()
    fake_dialog_instance = MagicMock()
    fake_dialog_instance.success = False
    fake_dialog_cls.return_value = fake_dialog_instance

    parent = MagicMock()
    # wait_window is called via self.app.wait_window — wire it on
    # the fake app.
    app.wait_window = MagicMock()  # type: ignore[attr-defined]

    with patch.object(svc, "start_worker", side_effect=fake_start_worker), \
         patch.object(svc, "retire_worker", side_effect=fake_retire), \
         patch("app.dialogs.model_loading.ModelLoadingDialog", fake_dialog_cls):
        result = svc.ensure_worker_ready(parent)

    assert result is False, "Cancel path must return False"
    assert len(spawned) == 1, "Should have spawned exactly one worker"
    assert spawned[0] in retired, (
        "Cancelled worker must be retired/torn down — found "
        f"retired={[w['id'] for w in retired]}"
    )
    # Sanity: pending_load slots cleared.
    assert svc._pending_load_worker_id is None
    assert svc._pending_load_dialog is None
    assert svc._pending_load_event is None
