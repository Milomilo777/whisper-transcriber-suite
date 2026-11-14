"""A selection callback must drain queued events without feeding itself."""
from __future__ import annotations

from collections import deque
import threading
from pathlib import Path
from types import MethodType, SimpleNamespace

import pytest

from app.widgets.hardware_wizard import HardwareWizard


class QueuedTree:
    """Deliver selection events later, after the synchronous guard resets."""

    def __init__(self) -> None:
        self.events: deque[None] = deque()
        self.focused = ""
        self.selection_calls = 0
        self.focus_writes = 0
        self.marks = {"0": "", "1": ""}

    def get_children(self) -> tuple[str, ...]:
        return tuple(self.marks)

    def set(self, item: str, column: str, value: str) -> None:
        assert column == "pick"
        self.marks[item] = value

    def selection_set(self, item: str) -> None:
        assert item in self.marks
        self.selection_calls += 1
        self.events.append(None)

    def focus(self, item: str | None = None) -> str:
        if item is not None:
            self.focus_writes += 1
            self.focused = item
        return self.focused


def wizard_harness() -> SimpleNamespace:
    assert Path(HardwareWizard._on_select.__code__.co_filename).resolve().is_relative_to(
        Path(__file__).resolve().parents[2]
    )
    tree = QueuedTree()
    status = SimpleNamespace(value="", set=lambda value: setattr(status, "value", value))
    wizard = SimpleNamespace(
        tree=tree, status_var=status, _selected_idx=None, _selecting=False,
        _user_picked=False, save_sync_calls=0,
        _tiers=[
            SimpleNamespace(backend="faster_whisper", label="CPU tier", device="cpu", compute_type="int8"),
            SimpleNamespace(backend="faster_whisper", label="GPU tier", device="cuda", compute_type="float16"),
        ],
    )
    wizard._sync_save_button = lambda: setattr(wizard, "save_sync_calls", wizard.save_sync_calls + 1)
    wizard._select_index = MethodType(HardwareWizard._select_index, wizard)
    return wizard


@pytest.mark.parametrize("row", ["0", "1"])
def test_selection_callback_reads_widget_without_rewriting_it(row: str) -> None:
    wizard = wizard_harness()
    wizard.tree.focus(row)
    writes_before = wizard.tree.focus_writes

    HardwareWizard._on_select(wizard, None)

    assert wizard.tree.selection_calls == 0
    assert wizard.tree.focus_writes == writes_before
    assert wizard._selected_idx == int(row)
    assert wizard._user_picked
    assert wizard.save_sync_calls == 1
    assert wizard.tree.marks[row] == "\u2713"
    assert wizard._tiers[int(row)].label in wizard.status_var.value


def drain_selection_events(wizard: SimpleNamespace, limit: int = 8) -> int:
    delivered = 0
    while wizard.tree.events and delivered < limit:
        wizard.tree.events.popleft()
        HardwareWizard._on_select(wizard, None)
        delivered += 1
    return delivered


def test_user_selection_does_not_keep_requeuing_itself() -> None:
    wizard = wizard_harness()
    wizard.tree.focus("1")
    wizard.tree.selection_set("1")

    delivered = drain_selection_events(wizard)

    assert not wizard.tree.events, "A selection event continually requeued itself"
    assert delivered == 1
    assert wizard.tree.selection_calls == 1
    assert wizard._selected_idx == 1
    assert wizard._user_picked
    assert wizard.tree.marks == {"0": "", "1": "\u2713"}
    assert "GPU tier" in wizard.status_var.value


def test_explicit_programmatic_selection_still_sets_widget_once() -> None:
    wizard = wizard_harness()

    wizard._select_index(1)
    drain_selection_events(wizard)

    assert not wizard.tree.events
    assert wizard.tree.selection_calls == 1
    assert wizard.tree.focus() == "1"
    assert wizard._selected_idx == 1


def test_empty_focus_is_ignored_without_changing_the_pick() -> None:
    wizard = wizard_harness()
    HardwareWizard._on_select(wizard, None)
    assert wizard._selected_idx is None
    assert not wizard._user_picked
    assert not wizard.tree.events


@pytest.mark.parametrize("row", ["not-a-tier", "cuda_unusable"])
def test_non_tier_rows_do_not_rewrite_selection(row: str) -> None:
    wizard = wizard_harness()
    wizard._cuda_status = SimpleNamespace(summary=lambda: "Setup needed")
    wizard.tree.focus(row)
    writes_before = wizard.tree.focus_writes

    HardwareWizard._on_select(wizard, None)

    assert wizard._selected_idx is None
    assert not wizard._user_picked
    assert wizard.tree.selection_calls == 0
    assert wizard.tree.focus_writes == writes_before
    assert wizard.save_sync_calls == 0
    if row == "cuda_unusable":
        assert wizard.status_var.value == "Setup needed"


@pytest.mark.parametrize("alive, generation", [(False, 2), (True, 1)])
def test_closed_or_superseded_probe_cannot_apply_result(alive: bool, generation: int) -> None:
    wizard = SimpleNamespace(
        winfo_exists=lambda: alive, _probe_seq=2, _tiers=["unchanged"],
    )

    HardwareWizard._reprobe_done(wizard, generation, [], None)

    assert wizard._tiers == ["unchanged"]


def test_cancel_then_late_result_does_not_apply_a_pick() -> None:
    state = {"alive": True, "released": False}
    wizard = SimpleNamespace(
        winfo_exists=lambda: state["alive"], _probe_seq=2, _tiers=["unchanged"],
        _master_had_grab=False, _probe_lock=threading.Lock(), _probe_result=None, _probe_after_id=None,
        grab_release=lambda: state.update(released=True),
        destroy=lambda: state.update(alive=False),
    )

    HardwareWizard._on_close(wizard)
    HardwareWizard._reprobe_done(wizard, 2, [], None)

    assert state == {"alive": False, "released": True}
    assert wizard._tiers == ["unchanged"]


def test_late_old_worker_cannot_replace_current_result(monkeypatch):
    from app.widgets import hardware_wizard as ui
    current = (2, ["current tier"], None)
    fake = SimpleNamespace(_probe_seq=2, _probe_lock=threading.Lock(), _probe_result=current)
    monkeypatch.setattr(ui._hw, "probe_hardware_snapshot", lambda: ([], None))
    monkeypatch.setattr(ui._hw, "probe_tiers", lambda *_: ["obsolete tier"])
    HardwareWizard._reprobe_worker(fake, 1)
    assert fake._probe_result is current
