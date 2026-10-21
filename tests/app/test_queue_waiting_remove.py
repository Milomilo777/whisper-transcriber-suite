"""A job that has not started yet can be removed from the Queue.

Remove was greyed out for a waiting row with no reason; the way out was Cancel, then
Remove (code review, 2026-10-21). Windowless: fakes stand in for Tk.
"""
from __future__ import annotations

import types

from app.app import App


def _fake(selected: list) -> types.SimpleNamespace:
    removed: list = []
    fake = types.SimpleNamespace(
        queue=list(selected), _selected_tasks=lambda: selected, removed=removed,
        _update_queue_action_bar=lambda: None,
    )
    fake._action_bar_apply = App._action_bar_apply.__get__(fake)
    return fake


def test_remove_takes_a_waiting_job_off_the_list() -> None:
    waiting = types.SimpleNamespace(status="waiting")
    fake = _fake([waiting])
    fake._action_bar_apply(lambda t: fake.removed.append(t), active_only=False, also_waiting=True)
    assert fake.removed == [waiting]


def test_rerun_still_skips_a_waiting_job() -> None:
    waiting = types.SimpleNamespace(status="waiting")
    fake = _fake([waiting])
    fake._action_bar_apply(lambda t: fake.removed.append(t), active_only=False)
    assert fake.removed == []


def test_the_remove_button_passes_also_waiting() -> None:
    import inspect

    from app.widgets import tabs

    assert "app._action_bar_apply(app.remove_task, active_only=False, also_waiting=True)" in \
        inspect.getsource(tabs.build_queue_tab)


def test_the_menu_offers_remove_for_a_waiting_row() -> None:
    import inspect

    src = inspect.getsource(App.menu_row)
    assert 'if task.status == "waiting" and states["remove"]:' in src


def test_removing_a_waiting_job_releases_the_download_that_waits_on_it(monkeypatch) -> None:
    """A job queued by "transcribe after download" kept its Download row "transcribing"
    for good when it was removed before it started (review, 2026-10-21)."""
    import app.app as app_mod

    ended: list = []
    monkeypatch.setattr(app_mod.desktop_alert, "job_ended", lambda _app, t: ended.append(t))
    dl = types.SimpleNamespace(status="transcribing", make_subbed_video=False, transcription_task=None)
    task = types.SimpleNamespace(status="waiting", source_download=dl)
    dl.transcription_task = task
    fake = types.SimpleNamespace(queue=[task], refresh=lambda: None, refresh_download_queue=lambda: None)
    fake._release_waiting_download = App._release_waiting_download.__get__(fake)
    App.remove_task(fake, task)  # type: ignore[arg-type]
    assert fake.queue == [] and dl.status == "finished" and dl.transcription_task is None
    assert ended == [task]


def test_removing_a_finished_job_leaves_its_download_alone(monkeypatch) -> None:
    import app.app as app_mod

    monkeypatch.setattr(app_mod.desktop_alert, "job_ended", lambda *_a: None)
    dl = types.SimpleNamespace(status="finished")
    task = types.SimpleNamespace(status="finished", source_download=dl)
    fake = types.SimpleNamespace(queue=[task], refresh=lambda: None)
    App.remove_task(fake, task)  # type: ignore[arg-type]
    assert fake.queue == [] and dl.status == "finished"
