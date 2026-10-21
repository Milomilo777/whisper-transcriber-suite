"""The Queue selects a job when it starts, so Pause and Cancel work at once.

The action bar follows the selection only, and nothing selected a running job: a
click-through test and two screenshot reviews found Pause and Cancel greyed out while a
job ran (2026-10-21). Windowless: a fake tree stands in for the Treeview.
"""
from __future__ import annotations

import types

from app.app import App


class _Tree:
    def __init__(self) -> None:
        self.selected: tuple[str, ...] = ()
        self.seen: list[str] = []

    def selection(self) -> tuple[str, ...]:
        return self.selected

    def selection_set(self, items) -> None:
        self.selected = tuple(items) if isinstance(items, (list, tuple)) else (items,)

    def see(self, item: str) -> None:
        self.seen.append(item)


def _fake(*statuses: str) -> types.SimpleNamespace:
    tasks = [types.SimpleNamespace(status=s) for s in statuses]
    fake = types.SimpleNamespace(
        tree=_Tree(), queue=tasks, row_map={f"I{i}": t for i, t in enumerate(tasks)},
    )
    fake._auto_select_running_row = App._auto_select_running_row.__get__(fake)
    return fake


def test_a_job_that_starts_is_selected() -> None:
    fake = _fake("finished", "running", "waiting")
    fake._auto_select_running_row()
    assert fake.tree.selected == ("I1",) and fake.tree.seen == ["I1"]


def test_a_selection_the_user_made_is_kept() -> None:
    fake = _fake("waiting", "running")
    fake.tree.selected = ("I0",)
    fake._auto_select_running_row()
    assert fake.tree.selected == ("I0",)


def test_an_ended_row_left_selected_gives_way_to_the_running_job() -> None:
    """A finished row left selected kept Pause and Cancel grey for the next job
    (screenshot review, 2026-10-21)."""
    fake = _fake("finished", "running")
    fake.tree.selected = ("I0",)
    fake._auto_select_running_row()
    assert fake.tree.selected == ("I1",)


def test_the_same_job_is_selected_only_once() -> None:
    fake = _fake("running")
    fake._auto_select_running_row()
    fake.tree.selected = ()  # the user cleared it
    fake._auto_select_running_row()
    assert fake.tree.selected == ()


def test_the_next_job_is_selected_when_it_starts() -> None:
    fake = _fake("running", "waiting")
    fake._auto_select_running_row()
    fake.queue[0].status, fake.queue[1].status = "finished", "running"
    fake.tree.selected = ()
    fake._auto_select_running_row()
    assert fake.tree.selected == ("I1",)


def test_several_running_jobs_pick_none() -> None:
    fake = _fake("running", "running")
    fake._auto_select_running_row()
    assert fake.tree.selected == ()


def test_refresh_calls_it() -> None:
    import inspect

    assert "_auto_select_running_row()" in inspect.getsource(App.refresh)
