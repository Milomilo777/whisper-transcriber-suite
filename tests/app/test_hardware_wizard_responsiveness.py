"""Real Tk queue, responsiveness and cancellation regressions; no hardware work."""
from __future__ import annotations

import _tkinter
import threading
import time
import tkinter as tk

import pytest

from app.widgets import hardware_wizard as ui
from core import hardware as hw


def pump(root, seconds=0.15, budget=2000):
    end = time.monotonic() + seconds
    count = 0
    while time.monotonic() < end and count < budget:
        if root.tk.dooneevent(_tkinter.ALL_EVENTS | _tkinter.DONT_WAIT):
            count += 1
        else:
            time.sleep(0.001)
    return count


@pytest.fixture
def window(monkeypatch, tmp_path):
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path / "profile"))
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(False, False))
    monkeypatch.setattr(hw, "probe_tiers", lambda *_: [
        hw.Tier("cpu_int8", "CPU tier", "cpu", "int8"),
        hw.Tier("cuda_float16", "GPU tier", "cuda", "float16"),
    ])
    root = tk.Tk()
    root.withdraw()
    root.grab_set()
    wizard = ui.HardwareWizard(root)
    wizard.withdraw()
    assert wizard._probe_thread is not None
    wizard._probe_thread.join(timeout=1)
    pump(root, 0.08)
    assert not wizard._busy
    try:
        yield root, wizard
    finally:
        if wizard.winfo_exists():
            wizard._on_close()
        root.destroy()


def test_real_tree_selection_queue_drains(window):
    root, wizard = window
    events = []
    wizard.tree.bind("<<TreeviewSelect>>", lambda _e: events.append(1), add="+")
    wizard.tree.focus("1")
    wizard.tree.selection_set("1")
    processed = pump(root, 0.15, 512)
    assert processed < 512, "Actual Tk selection queue kept feeding itself"
    assert 1 <= len(events) <= 2
    assert wizard._selected_idx == 1 and wizard._user_picked
    assert wizard.tree.set("1", "pick") == "\u2713"
    assert not wizard.save_btn.instate(["disabled"])


def test_repeated_selections_leave_timer_heartbeats_responsive(window):
    root, wizard = window
    ticks = []
    def beat():
        ticks.append(time.monotonic())
        if len(ticks) < 8:
            root.after(10, beat)
    root.after(10, beat)
    for row in ["1", "0", "1", "0"]:
        wizard.tree.focus(row)
        wizard.tree.selection_set(row)
        pump(root, 0.04, 512)
    pump(root, 0.1, 512)
    assert len(ticks) == 8, "Selection processing starved the real Tk timer queue"
    assert wizard._selected_idx == 0


def test_slow_probe_times_out_without_pinning_cpu_and_late_result_is_ignored(window, monkeypatch):
    root, wizard = window
    wizard.tree.focus("1")
    wizard.tree.selection_set("1")
    pump(root, 0.04)
    assert wizard._user_picked and wizard._selected_idx == 1
    release = threading.Event()
    entered = threading.Event()
    calls = []
    def blocked():
        calls.append(1)
        entered.set()
        assert release.wait(5)
        return hw.CudaStatus(False, False)
    monkeypatch.setattr(hw, "cuda_status", blocked)
    monkeypatch.setattr(ui.HardwareWizard, "PROBE_TIMEOUT_S", 0.03, raising=False)
    wizard._reprobe()
    thread = wizard._probe_thread
    assert entered.wait(1)
    ticks = []
    root.after(10, lambda: ticks.append(1))
    try:
        pump(root, 0.15)
        assert ticks == [1]
        assert not wizard._busy, "A blocked detector leaves the wizard disabled forever"
        assert not wizard.reprobe_btn.instate(["disabled"])
        assert wizard.save_btn.instate(["disabled"]), "Timeout must require an explicit CPU choice"
        assert wizard._selected_idx == -1 and not wizard._user_picked
        assert [t.device for t in wizard._tiers] == ["cpu"]
        wizard._reprobe()
        assert wizard._probe_thread is thread, "Do not stack another blocked native probe"
        assert calls == [1]
        selected = list(wizard._tiers)
    finally:
        release.set()
        assert thread is not None
        thread.join(timeout=1)
    pump(root, 0.08)
    assert wizard._tiers == selected
    assert wizard._probe_result is None


def test_cancel_returns_while_detector_is_blocked_and_restores_master_grab(window, monkeypatch):
    root, wizard = window
    release = threading.Event()
    entered = threading.Event()
    def blocked():
        entered.set()
        assert release.wait(5)
        return hw.CudaStatus(False, False)
    monkeypatch.setattr(hw, "cuda_status", blocked)
    wizard._reprobe()
    assert entered.wait(1)
    thread = wizard._probe_thread
    started = time.monotonic()
    try:
        wizard._on_close()
        assert time.monotonic() - started < 0.2
        assert not wizard.winfo_exists()
        assert root.grab_current() is root
        ticks = []
        root.after(10, lambda: ticks.append(1))
        pump(root, 0.05)
        assert ticks == [1]
    finally:
        release.set()
        assert thread is not None
        thread.join(timeout=1)
    assert wizard._probe_result is None, "Cancelled wizard retained its obsolete worker result"


def test_repeated_completed_reprobes_keep_one_poll_and_a_live_timer(window):
    root, wizard = window
    ticks = []
    for _ in range(5):
        wizard._reprobe()
        poll = wizard._probe_after_id
        wizard._schedule_probe_poll()
        assert wizard._probe_after_id == poll
        assert wizard._probe_thread is not None
        wizard._probe_thread.join(timeout=1)
        root.after(10, lambda: ticks.append(1))
        pump(root, 0.08)
        assert not wizard._busy
        assert wizard._probe_after_id is None
        assert len(wizard._tiers) == 2
    assert len(ticks) == 5


def test_timeout_can_retry_once_old_detector_finishes(window, monkeypatch):
    root, wizard = window
    release = threading.Event()
    def blocked():
        assert release.wait(5)
        return hw.CudaStatus(False, False)
    monkeypatch.setattr(hw, "cuda_status", blocked)
    monkeypatch.setattr(ui.HardwareWizard, "PROBE_TIMEOUT_S", 0.03)
    wizard._reprobe()
    thread = wizard._probe_thread
    try:
        pump(root, 0.15)
        assert not wizard._busy
        assert wizard._selected_idx == -1
        wizard.tree.focus("0")
        wizard.tree.selection_set("0")
        pump(root, 0.04)
        assert wizard._user_picked
        assert not wizard.save_btn.instate(["disabled"])
    finally:
        release.set()
        assert thread is not None
        thread.join(timeout=1)
    monkeypatch.setattr(hw, "cuda_status", lambda: hw.CudaStatus(False, False))
    monkeypatch.setattr(ui.HardwareWizard, "PROBE_TIMEOUT_S", 1)
    wizard._reprobe()
    assert wizard._probe_thread is not thread
    wizard._probe_thread.join(timeout=1)
    pump(root, 0.08)
    assert not wizard._busy
    assert len(wizard._tiers) == 2
    assert not wizard._user_picked
