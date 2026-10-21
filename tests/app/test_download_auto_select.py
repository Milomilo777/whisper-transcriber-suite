"""The Download tab selects a download when it starts, so Pause and Cancel work at once.

Same gap the Queue had: the action bar follows the selection only, so while a download ran
Pause, Cancel and Open stayed grey until the user found its row (round-2 screenshot critics,
2026-10-21; verified in code). The finished row then stays selected and Open works.
Windowless: a fake tree stands in for the Treeview.
"""
from __future__ import annotations

import types

from app.app import App
from tests.app.test_queue_auto_select import _Tree


def _fake(*statuses: str) -> types.SimpleNamespace:
    tasks = [types.SimpleNamespace(status=s) for s in statuses]
    fake = types.SimpleNamespace(
        download_tree=_Tree(), download_queue=tasks,
        download_row_map={f"D{i}": t for i, t in enumerate(tasks)},
    )
    fake._auto_select_running_download = App._auto_select_running_download.__get__(fake)
    return fake


def test_a_download_that_starts_is_selected() -> None:
    fake = _fake("finished", "running")
    fake._auto_select_running_download()
    assert fake.download_tree.selected == ("D1",) and fake.download_tree.seen == ["D1"]


def test_a_finished_row_left_selected_gives_way_to_the_running_download() -> None:
    fake = _fake("finished", "running")
    fake.download_tree.selected = ("D0",)
    fake._auto_select_running_download()
    assert fake.download_tree.selected == ("D1",)


def test_a_paused_row_the_user_picked_is_kept() -> None:
    fake = _fake("paused", "running")
    fake.download_tree.selected = ("D0",)
    fake._auto_select_running_download()
    assert fake.download_tree.selected == ("D0",)


def test_the_same_download_is_selected_only_once() -> None:
    fake = _fake("running")
    fake._auto_select_running_download()
    fake.download_tree.selected = ()  # the user cleared it
    fake._auto_select_running_download()
    assert fake.download_tree.selected == ()


def test_two_running_downloads_select_nothing() -> None:
    fake = _fake("running", "running")
    fake._auto_select_running_download()
    assert fake.download_tree.selected == ()


def test_the_table_refresh_selects_the_running_download() -> None:
    from tests.core.test_thread_marshalling_and_selection import (
        _download_task, _fake_download_refresh_app,
    )

    task = _download_task("v0")
    task.status = "running"
    app = _fake_download_refresh_app([task])
    app._auto_select_running_download = App._auto_select_running_download.__get__(app)
    App.refresh_download_queue(app)  # type: ignore[arg-type]
    assert tuple(app.download_tree.selection()) == tuple(app.download_tree.get_children())
