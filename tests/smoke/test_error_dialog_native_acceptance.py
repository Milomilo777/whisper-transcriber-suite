"""Standalone native Windows Tk acceptance tests; run on an interactive desktop.

Run standalone with --noconftest: the tree otherwise installs a fake display.
The runner must supply the immutable application snapshot through PYTHONPATH.
These tests do not repair focus or stacking after show_error; failures are data.
"""
from __future__ import annotations

import json
import sys
import time
import tkinter as tk
from tkinter import ttk

import pytest

from app.widgets.error_dialog import show_error


def _pump(root: tk.Tk, seconds: float = 0.3) -> None:
    """Process native Map/Unmap/focus events for a bounded interval."""
    deadline = time.monotonic() + seconds
    while True:
        root.update()
        if time.monotonic() >= deadline:
            break
        time.sleep(0.01)


@pytest.fixture
def native_root(record_property):
    if sys.platform != "win32":
        pytest.fail("Native Windows interactive Tk desktop required (no skip).")
    root = None
    callback_errors = []
    try:
        try:
            root = tk.Tk()
        except tk.TclError as exc:
            pytest.fail(f"Cannot create native desktop Tk: {exc}")
        root.report_callback_exception = lambda *error: callback_errors.append(repr(error))
        system = root.tk.call("tk", "windowingsystem")
        assert system == "win32", f"Native win32 Tk required, got {system!r}"
        record_property("tk_patchlevel", str(root.tk.call("info", "patchlevel")))
        root.title("P17 native acceptance host")
        root.geometry("640x400+100+100")
        root.deiconify()
        root.lift()
        root.focus_force()
        _pump(root)
        assert root.winfo_viewable(), "Native desktop root did not become viewable"
        assert str(root.tk.call("focus")) == str(root), "Desktop cannot focus native Tk root"
        yield root
    finally:
        if root is not None:
            # A raw Tcl popdown may have no Python wrapper; release through Tcl.
            try:
                if root.tk.call("winfo", "exists", "."):
                    current = root.tk.call("grab", "current", ".")
                    if current:
                        root.tk.call("grab", "release", current)
                    root.destroy()
            finally:
                record_property("callback_errors", json.dumps(callback_errors))
        assert not callback_errors, f"Native Tk callback failures: {callback_errors}"


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _error(root, parent, title):
    before = {str(widget) for widget in _descendants(root)}
    show_error(parent, title, "Native modal acceptance message")
    _pump(root)
    candidates = [
        widget for widget in _descendants(root)
        if isinstance(widget, tk.Toplevel) and str(widget) not in before
        and widget.title() == title
    ]
    assert len(candidates) == 1, f"Expected one new error, found {candidates}"
    top = candidates[0]
    buttons = [widget for widget in _descendants(top) if isinstance(widget, ttk.Button)]
    assert len(buttons) == 1, f"Expected sole OK button, found {buttons}"
    return top, buttons[0]


def _observe(root, top, ok, record_property, phase):
    state = {
        "root_state": root.state(),
        "error_viewable": bool(top.winfo_viewable()),
        "error_transient": str(top.transient()),
        "grab": str(root.tk.call("grab", "current", ".")),
        "focus": str(root.tk.call("focus")),
        "error": str(top),
        "ok": str(ok),
    }
    if root.winfo_viewable() and top.winfo_viewable():
        state["error_above_root"] = bool(int(root.tk.call("wm", "stackorder", str(top), "isabove", str(root))))
        state["stackorder"] = str(root.tk.call("wm", "stackorder", "."))
    record_property(phase, json.dumps(state, sort_keys=True))
    return state


def _assert_modal_focused(state):
    assert state["error_viewable"], state
    assert state["grab"] == state["error"], state
    assert state["focus"] == state["ok"], state


def test_real_combobox_popdown_restores_modal_host(native_root, record_property):
    root = native_root
    host = tk.Toplevel(root)
    host.transient(root)
    host.geometry("400x200+200+200")
    combo = ttk.Combobox(host, values=("first", "second"), state="readonly")
    combo.pack(padx=20, pady=20)
    combo.current(0)
    _pump(root)
    host.grab_set()
    combo.focus_force()
    root.tk.call("ttk::combobox::Post", str(combo))
    _pump(root)
    popdown = str(root.tk.call("ttk::combobox::PopdownWindow", str(combo)))
    posted_grab = str(root.tk.call("grab", "current", "."))
    record_property("posted_popdown", json.dumps({"popdown": popdown, "grab": posted_grab}))
    assert posted_grab == popdown, f"Real combobox did not acquire grab: {posted_grab!r}, {popdown!r}"
    assert int(root.tk.call("winfo", "viewable", popdown)), "Real popdown was not mapped"
    top, ok = _error(root, host, "P17 combobox error")
    state = _observe(root, top, ok, record_property, "error_after_unmap_events")
    _assert_modal_focused(state)
    ok.invoke()
    _pump(root)
    restored = str(root.tk.call("grab", "current", "."))
    record_property("restored_host_grab", restored)
    assert not top.winfo_exists(), "OK.invoke did not destroy the error"
    assert restored == str(host), f"Expected modal host {host}, got grab {restored!r}"


@pytest.mark.parametrize("hidden_state", ["withdrawn", "iconic"])
def test_hidden_owner_restore_keeps_error_above_and_focused(native_root, record_property, hidden_state):
    root = native_root
    if hidden_state == "withdrawn":
        root.withdraw()
    else:
        root.iconify()
    _pump(root)
    assert root.state() == hidden_state, f"Failed to establish {hidden_state}: {root.state()}"
    assert not root.winfo_viewable(), "Hidden owner remained viewable"
    top, ok = _error(root, root, "P17 hidden owner error")
    before = _observe(root, top, ok, record_property, "before_owner_restore")
    assert before["error_viewable"] and before["grab"] == str(top), before
    # Exact tray restore sequence. Do not help the dialog recover afterwards.
    root.deiconify()
    root.lift()
    root.focus_force()
    _pump(root)
    state = _observe(root, top, ok, record_property, "after_owner_restore")
    assert root.winfo_viewable(), state
    # Report all three acceptance outcomes even if stacking is the first failure.
    failures = []
    if not state.get("error_above_root", False):
        failures.append("error is not above restored root")
    if state["grab"] != str(top):
        failures.append("error lost grab")
    if state["focus"] != str(ok):
        failures.append("OK lost focus")
    assert not failures, f"{failures}; native observation={state}"


def test_viewability_tclerror_creates_unowned_modal_error(native_root, record_property):
    root = native_root
    original = root.winfo_viewable

    def unavailable_viewability():
        raise tk.TclError("P17 deliberate instance viewability failure")

    # Fault only the instance probe; every window and all other Tk calls are real.
    root.winfo_viewable = unavailable_viewability
    try:
        top, ok = _error(root, root, "P17 viewability fallback error")
    finally:
        root.winfo_viewable = original
    state = _observe(root, top, ok, record_property, "viewability_exception_fallback")
    assert state["error_transient"] == "", state
    _assert_modal_focused(state)
    ok.invoke()
    _pump(root)
    restored = str(root.tk.call("grab", "current", "."))
    record_property("fallback_closed_grab", restored)
    assert not top.winfo_exists(), "Fallback error did not close"
    assert restored == "", f"Fallback left grab {restored!r}"
    assert root.winfo_exists() and root.winfo_viewable(), "Fallback damaged visible owner"


def test_hidden_notebook_frame_keeps_visible_toplevel_owner(native_root, record_property):
    root = native_root
    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)
    selected = ttk.Frame(notebook)
    hidden = ttk.Frame(notebook)
    notebook.add(selected, text="Visible")
    notebook.add(hidden, text="Unselected")
    notebook.select(selected)
    _pump(root)
    assert root.winfo_viewable(), "Root prerequisite failed"
    assert not hidden.winfo_viewable(), "Notebook parent must be in an unmapped tab"
    top, ok = _error(root, hidden, "P17 hidden tab error")
    state = _observe(root, top, ok, record_property, "hidden_tab_parent")
    assert state["error_transient"] == str(root), state
    _assert_modal_focused(state)
