"""The Download tab's lookup line sits right under the link box.

"Found: Me at the zoo (0:19)" (or why a link cannot be read) was gridded ~350 px lower, under
the subtitle options, far from the box it is about (round-2 screenshot critics, 2026-10-21).
Needs Tk.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets import tabs
from tests.app.test_i18n_wave_4 import _StubApp


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError as exc:  # pragma: no cover - no display
        pytest.skip(f"no Tk display: {exc}")
    r.withdraw()
    yield r
    r.destroy()


def test_the_lookup_line_is_packed_right_under_the_link_box(root):
    app = _StubApp(root)
    frame = ttk.Frame(root)
    tabs.build_download_tab(app, frame)  # type: ignore[arg-type]
    entry = next(w for w in root.nametowidget(str(app.format_status_label.master.master)).winfo_children()
                 if isinstance(w, ttk.Entry))
    cell = entry.master
    assert str(entry.cget("textvariable")) == str(app.download_url_var)
    packed = cell.pack_slaves()
    assert packed.index(entry) + 1 == packed.index(app.format_status_label.master)
