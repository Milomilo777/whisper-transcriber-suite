"""conftest cancels a root's pending after() calls when the root is destroyed."""
from __future__ import annotations

import tkinter as tk

import pytest


def test_a_destroyed_root_leaves_no_pending_timer() -> None:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no Tk display")
    root.withdraw()
    interp = root.tk
    root.after(60000, lambda: None)
    root.after_idle(lambda: None)
    assert interp.splitlist(interp.call("after", "info")), "control: timers are pending"
    root.destroy()
    assert not interp.splitlist(interp.call("after", "info"))
