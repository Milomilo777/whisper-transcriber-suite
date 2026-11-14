"""Actual notice handlers with inert widget adapters; never create Tcl/Tk."""
from __future__ import annotations

import _tkinter
import tkinter as tk
from types import SimpleNamespace

import pytest

from app.widgets import notice


class Widget:
    def __init__(self, window=None, **kwargs):
        self.window = window or self
        self.bindings = {}
        self.mapped = False
        self.value = None
        self.tk = self
        self.focused = None
        self.cancelled = []
        self.timers = {}
        self.command = kwargs.get("command")

    def __str__(self):
        return f"widget-{id(self)}"

    def bind(self, sequence, callback, **kwargs):
        self.bindings[sequence] = callback

    def pack(self, **kwargs):
        pass

    def place(self, **kwargs):
        self.mapped = True

    def place_forget(self):
        self.mapped = False
        # Unmapping deliberately leaves focus alone: this models the stated
        # native premise; native platform confirmation remains separate QA.

    def lift(self):
        pass

    def set(self, value):
        self.value = value

    def configure(self, **kwargs):
        pass

    def call(self, *args):
        assert args[0] == "focus"
        return str(self.focused) if self.focused is not None else ""

    def focus_get(self):
        return self.focused

    def focus_set(self):
        self.window.focused = self

    def after(self, ms, callback):
        key = str(len(self.timers) + len(self.cancelled))
        self.timers[key] = callback
        return key

    def after_cancel(self, key):
        self.cancelled.append(key)
        self.timers.pop(key, None)


@pytest.fixture(autouse=True)
def forbid_tk(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("native Tcl/Tk creation forbidden in this suite")
    monkeypatch.setattr(_tkinter, "create", forbidden)


@pytest.fixture
def host(monkeypatch):
    monkeypatch.setattr(notice.sys, "platform", "win32")
    for module, names in ((notice.ttk, ("Frame", "Separator", "Label", "Button")),
                          (notice.tk, ("Frame", "StringVar"))):
        for name in names:
            monkeypatch.setattr(module, name, Widget)
    window = Widget()
    return notice.NoticeHost(window)


@pytest.mark.parametrize("sequence", ["<Escape>", "<Return>", "<KP_Enter>"])
def test_visible_close_key_consumes_only_notice_action(host, sequence):
    host.post("Saved")
    host.window.focused = host.close_button
    handler = host.close_button.bindings.get(sequence)
    assert handler is not None, f"missing actual close-button binding: {sequence}"
    assert handler(SimpleNamespace(widget=host.close_button)) == "break"
    assert not host.visible
    assert host.window.focused is host.window


@pytest.mark.parametrize("sequence", ["<Escape>", "<Return>", "<KP_Enter>"])
def test_hidden_notice_key_propagates_to_host_default(host, sequence):
    host.post("Saved")
    host.dismiss()
    handler = host.close_button.bindings.get(sequence)
    assert handler is not None, f"missing actual close-button binding: {sequence}"
    default_actions = []
    if handler() != "break":
        default_actions.append(sequence)
    assert default_actions == [sequence]


@pytest.mark.parametrize("via_timer", [False, True])
def test_hide_releases_focused_close_and_preserves_timer_cancellation(host, via_timer):
    host.post("Saved")
    timer = host._after_id
    host.window.focused = host.close_button
    if via_timer:
        host._on_timeout()
    else:
        host.dismiss()
        assert timer in host.window.cancelled
    assert not host.visible and not host.frame.mapped
    assert host.window.focused is host.window
    assert host._after_id is None


def test_notice_does_not_steal_focus_from_later_widget(host):
    host.post("Saved")
    other = Widget(host.window)
    host.window.focused = other
    host.dismiss()
    assert host.window.focused is other
    host.post("Again")
    assert host.visible and host.frame.mapped
    assert host.window.focused is other


def test_queued_notice_retains_focused_visible_close(host):
    host.post("First")
    host.post("Second")
    host.window.focused = host.close_button
    timer = host._after_id
    host.dismiss()
    assert timer in host.window.cancelled
    assert host.visible and host.current == ("Second", "info")
    assert host.window.focused is host.close_button
    host.dismiss()
    assert host.window.focused is host.window


def test_window_dismiss_shortcut_already_propagates_when_hidden(host):
    assert host._on_dismiss_key() is None
    host.post("Saved")
    assert host._on_dismiss_key() == "break"
    assert host._on_dismiss_key() is None


def test_teardown_focus_error_does_not_prevent_hiding(host, monkeypatch):
    host.post("Saved")
    def gone(*args):
        raise tk.TclError("window destroyed")
    monkeypatch.setattr(host.window, "call", gone)
    host.dismiss()
    assert not host.visible and not host.frame.mapped


def test_button_command_keeps_space_and_pointer_activation_path(host):
    host.post("Saved")
    host.window.focused = host.close_button
    host.close_button.command()
    assert not host.visible
    assert host.window.focused is host.window


def test_native_interpreter_creation_is_guarded():
    with pytest.raises(AssertionError, match="native Tcl/Tk creation forbidden"):
        _tkinter.create()
