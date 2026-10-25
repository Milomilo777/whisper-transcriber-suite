"""A job submitted through the built-in server counts as active for Exit and "Restart now".

Fakes only: no Tk window, no socket.
"""
from __future__ import annotations

import types
from typing import Any

from app import app as app_module
from app.app import App
from app.dialogs import ui_language
from core.server import ServerHandle


class _Manager:
    def __init__(self, counts: dict[str, int] | Exception) -> None:
        self._counts = counts

    def queue_counts(self) -> dict[str, int]:
        if isinstance(self._counts, Exception):
            raise self._counts
        return self._counts


def _handle(counts: dict[str, int] | Exception | None) -> ServerHandle:
    handle = ServerHandle(transcribe_fn=lambda *a, **k: None, load_model=False)
    if counts is not None:
        handle._manager = _Manager(counts)  # type: ignore[assignment]
    return handle


def test_handle_counts_queued_and_running_but_not_finished() -> None:
    assert _handle({"queued": 2, "running": 1, "finished": 9}).active_jobs() == 3
    assert _handle({"queued": 0, "running": 0, "finished": 9}).active_jobs() == 0


def test_handle_without_a_manager_or_with_a_failing_probe_is_idle() -> None:
    assert _handle(None).active_jobs() == 0
    assert _handle(RuntimeError("boom")).active_jobs() == 0


def test_app_reports_zero_without_a_server_and_the_count_with_one() -> None:
    assert App.active_server_jobs(types.SimpleNamespace()) == 0
    fake = types.SimpleNamespace(_server_handle=types.SimpleNamespace(active_jobs=lambda: 2))
    assert App.active_server_jobs(fake) == 2
    broken = types.SimpleNamespace(
        _server_handle=types.SimpleNamespace(active_jobs=lambda: 1 / 0))
    assert App.active_server_jobs(broken) == 0


def test_restart_offer_is_busy_while_a_server_job_runs() -> None:
    idle = types.SimpleNamespace(queue=[], download_queue=[], active_server_jobs=lambda: 0)
    busy = types.SimpleNamespace(queue=[], download_queue=[], active_server_jobs=lambda: 1)
    assert ui_language.jobs_running(idle) is False
    assert ui_language.jobs_running(busy) is True
    # An app object without the probe keeps the old behaviour.
    assert ui_language.jobs_running(types.SimpleNamespace(queue=[], download_queue=[])) is False


def _exit_self(server_jobs: int) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        _exit_from_tray=True,
        app_config={},
        tray=None,
        queue=[],
        download_queue=[],
        _closing=False,
        _exit_prompt_open=False,
        _server_handle=types.SimpleNamespace(active_jobs=lambda: server_jobs),
        destroy=lambda: (_ for _ in ()).throw(AssertionError("must not tear down")),
    )


def test_exit_asks_while_a_server_job_runs_and_stays_open_on_no(monkeypatch: Any) -> None:
    asked: list[tuple[Any, ...]] = []

    def no(*args: Any, **_k: Any) -> bool:
        asked.append(args)
        return False

    monkeypatch.setattr(app_module.messagebox, "askyesno", no)
    fake = _exit_self(1)
    App.on_exit(fake)  # type: ignore[arg-type]
    assert len(asked) == 1
    assert fake._closing is False and fake._exit_prompt_open is False
