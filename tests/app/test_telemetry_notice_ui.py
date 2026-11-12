"""Real Tk presentation of the usage-statistics disclosure (desktop runner)."""
from __future__ import annotations

import tkinter as tk
import time
from tkinter import ttk

import pytest

from app.services import telemetry_notice
from core import stats


def _wait_for_disclosure(root):
    deadline = time.monotonic() + 2
    ticks = []
    root.after(25, lambda: ticks.append(True))
    while not stats.telemetry_notice_seen(root.app_config) and time.monotonic() < deadline:
        root.update()
        time.sleep(0.01)
    root.update()
    assert stats.telemetry_notice_seen(root.app_config)
    assert ticks, "The event loop did not run while waiting for the mapped notice"


@pytest.fixture
def host(monkeypatch):
    root = tk.Tk()
    root.withdraw()
    root.geometry("760x300")
    root.app_config = {"telemetry_opt_in": True}  # type: ignore[attr-defined]
    root._closing = False  # type: ignore[attr-defined]
    root.nb = ttk.Notebook(root)  # type: ignore[attr-defined]
    page = ttk.Frame(root.nb)  # type: ignore[attr-defined]
    root.nb.add(page, text="Transcribe")  # type: ignore[attr-defined]
    entry = ttk.Entry(page)
    entry.pack()
    root.nb.pack(fill="both", expand=True)  # type: ignore[attr-defined]
    saved, ready = [], []
    monkeypatch.setattr(telemetry_notice, "save_config", lambda cfg: saved.append(dict(cfg)))
    controller = telemetry_notice.TelemetryNotice(root, on_ready=lambda: ready.append(True))
    try:
        yield root, entry, controller, saved, ready
    finally:
        for after_id in root.tk.call("after", "info"):
            root.after_cancel(after_id)
        root.destroy()


def test_real_notice_waits_for_mapping_and_keeps_keyboard_focus(host):
    root, entry, controller, saved, ready = host
    controller.start()
    root.update()
    assert not saved and not ready and controller._bar is None
    root.deiconify()
    root.update()
    entry.focus_force()
    root.update()
    controller._try_show()
    root.update()
    assert controller._bar.winfo_viewable()
    _wait_for_disclosure(root)
    assert len(saved) == len(ready) == 1
    assert root.focus_get() is entry
    assert root.pack_slaves().index(controller._bar) < root.pack_slaves().index(root.nb)


def test_real_turn_off_button_keeps_transcription_widgets_available(host):
    root, entry, controller, saved, ready = host
    root.deiconify()
    root.update()
    controller.start()
    root.update()
    _wait_for_disclosure(root)
    controller._bar.off_button.invoke()
    root.update()
    assert root.app_config["telemetry_opt_in"] is False
    assert saved[-1]["telemetry_opt_in"] is False
    assert not controller._bar.visible
    entry.insert(0, "Still usable")
    assert entry.get() == "Still usable"
