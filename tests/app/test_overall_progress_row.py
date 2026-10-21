"""The Queue's overall progress bar shows only while two or more jobs run, with a label.

It was a bare, always-present ttk bar: with one job it repeated the row's bar as a 1-px sliver
two round-2 critics could not place (verification pass 4, 2026-10-21). Windowless: fakes stand
in for the bar, its label and their row.
"""
from __future__ import annotations

import types

from app.app import App


class _Row:
    """Packed or not; never mapped, as inside a notebook tab that is not shown."""

    def __init__(self) -> None:
        self.shown = True
        self.packs = 0

    def pack(self, **_kw) -> None:
        self.shown = True
        self.packs += 1

    def pack_forget(self) -> None:
        self.shown = False

    def winfo_manager(self) -> str:
        return "pack" if self.shown else ""

    def winfo_ismapped(self) -> bool:
        return False


class _Var:
    def __init__(self) -> None:
        self.value = ""

    def set(self, value: str) -> None:
        self.value = value


def _fake(*progress: tuple[str, float]):
    queue = [types.SimpleNamespace(status=s, progress=p) for s, p in progress]
    return types.SimpleNamespace(queue=queue, pb={"value": 0}, overall_row=_Row(),
                                 overall_var=_Var())


def test_one_running_job_hides_the_overall_bar():
    fake = _fake(("running", 40.0), ("finished", 100.0))
    App.update_overall_progress(fake)  # type: ignore[arg-type]
    assert fake.overall_row.shown is False


def test_two_running_jobs_show_it_with_a_label():
    fake = _fake(("running", 40.0), ("running", 60.0), ("waiting", 0.0))
    App.update_overall_progress(fake)  # type: ignore[arg-type]
    assert fake.overall_row.shown is True
    assert fake.pb["value"] == 50.0
    assert fake.overall_var.value == "2 jobs running: 50% done in all"


def test_a_double_without_the_row_keeps_working():
    fake = types.SimpleNamespace(queue=[], pb={"value": 99})
    App.update_overall_progress(fake)  # type: ignore[arg-type]
    assert fake.pb["value"] == 0


def test_a_hidden_queue_tab_is_not_repacked_every_tick():
    # winfo_ismapped is False on a tab that is not shown: re-packing each 500 ms refresh kept an
    # idle window busy (review of f12f506f).
    fake = _fake(("running", 40.0), ("running", 60.0))
    fake.overall_row.shown = False
    for _tick in range(5):
        App.update_overall_progress(fake)  # type: ignore[arg-type]
    assert fake.overall_row.packs == 1
