"""Real error-dialog functions with inert adapters; no native Tk acceptance."""
from types import SimpleNamespace
import socket
import tkinter as tk

import pytest

from app.widgets import error_dialog


@pytest.fixture
def display(monkeypatch):
    def deny(*args, **kwargs):
        raise AssertionError('Native Tcl/Tk and network forbidden')
    monkeypatch.setattr(tk._tkinter, 'create', deny)
    monkeypatch.setattr(socket.socket, 'connect', deny)
    state = SimpleNamespace(widgets=[], windows=[], focus=None, commands=[])

    class Interpreter:
        holder = ''
        fail_lookup = False

        def call(self, *args):
            state.commands.append(args)
            if args[:2] == ('grab', 'current'):
                if self.fail_lookup:
                    self.fail_lookup = False
                    raise tk.TclError('synthetic unavailable grab query')
                return self.holder
            if args[:2] == ('grab', 'set'):
                self.holder = args[-1]
                return ''
            raise AssertionError('Unexpected interpreter operation: ' + repr(args))

    class Window(tk.Misc):
        def __init__(self, master=None):
            self.master, self.children, self.alive = master, {}, True
            self.bindings, self.protocols, self.callbacks = {}, {}, []
            self.tk = master.tk if master else Interpreter()
            self._w = '.' if master is None else master._w.rstrip('.') + '.w' + str(len(state.windows))
            if master:
                master.children[self._w.rsplit('.', 1)[-1]] = self
            state.windows.append(self)

        # grab_current/grab_set/_nametowidget are actual CPython Misc methods.
        def title(self, value): self.caption = value
        def transient(self, parent): pass
        def resizable(self, *args): pass
        def protocol(self, name, callback): self.protocols[name] = callback
        def bind(self, sequence, callback, **kwargs): self.bindings[sequence] = callback
        def update_idletasks(self): pass
        def winfo_rootx(self): return 100
        def winfo_rooty(self): return 100
        def winfo_width(self): return 400
        def winfo_height(self): return 300
        def winfo_screenwidth(self): return 1920
        def winfo_screenheight(self): return 1080
        def winfo_exists(self): return self.alive
        def wm_geometry(self, value): self.geometry_value = value
        def bell(self): pass
        def clipboard_clear(self): pass
        def clipboard_append(self, value): state.clipboard = value
        def after(self, delay, callback): self.callbacks.append(callback)
        def destroy(self):
            self.alive = False
            if self.tk.holder == self._w:
                self.tk.holder = ''
            if self.master:
                self.master.children.pop(self._w.rsplit('.', 1)[-1], None)

    class Top(Window):
        pass

    class Widget:
        def __init__(self, master, **options):
            self.master, self.options = master, options
            self.bindings = {}
            state.widgets.append(self)
        def bind(self, sequence, callback): self.bindings[sequence] = callback
        def invoke(self): return self.options['command']()
        def pack(self, **kwargs): pass
        def pack_forget(self): pass
        def configure(self, **options): self.options.update(options)
        def insert(self, index, text): self.text = text
        def yview(self, *args): pass
        def set(self, *args): pass
        def focus_set(self): state.focus = self

    monkeypatch.setattr(error_dialog.tk, 'Tk', Window)
    monkeypatch.setattr(error_dialog.tk, 'Toplevel', Top)
    monkeypatch.setattr(error_dialog.tk, 'Text', Widget)
    for name in ('Frame', 'Label', 'Button', 'Scrollbar'):
        monkeypatch.setattr(error_dialog.ttk, name, Widget)
    def no_font(*args, **kwargs):
        raise tk.TclError('inert font adapter')
    monkeypatch.setattr(error_dialog.tkfont, 'nametofont', no_font)
    monkeypatch.setattr(error_dialog, '_', lambda text: text)
    monkeypatch.setattr(error_dialog, 'plain', lambda text: text)
    monkeypatch.setattr(error_dialog, 'px', lambda value: value)
    monkeypatch.setattr(error_dialog.tokens, 'themed', lambda value: value)
    state.root, state.Top = Window(), Top
    return state


def assert_content_and_close(state):
    dialog = state.windows[-1]
    assert dialog.caption == 'Worker error'
    assert any(widget.options.get('text') == 'The worker failed.' for widget in state.widgets)
    assert any(widget.options.get('text') == 'Copy details' for widget in state.widgets)
    assert any(getattr(widget, 'text', None) == 'diagnostic detail' for widget in state.widgets)
    ok = next(widget for widget in state.widgets if widget.options.get('text') == 'OK')
    assert state.focus is ok
    assert state.root.grab_current() is dialog
    ok.options['command']()
    assert not dialog.alive


def show(state):
    error_dialog.show_error(state.root, 'Worker error', 'The worker failed.', detail='diagnostic detail')


def test_actual_cpython_grab_lookup_raises_for_tcl_only_path(display):
    display.root.tk.holder = '.raw.popdown'
    with pytest.raises(KeyError):
        display.root.grab_current()
    assert len(display.windows) == 1 and display.widgets == []


@pytest.mark.parametrize('queued_callback', [False, True])
def test_tcl_only_grab_still_delivers_error_content(display, queued_callback):
    display.root.tk.holder = '.raw.popdown'
    if queued_callback:
        # Scheduling/delivery adapter, not native after/event-loop coverage.
        display.root.after(0, lambda: show(display))
        display.root.callbacks.pop(0)()
    else:
        show(display)
    assert_content_and_close(display)
    assert display.root.grab_current() is None
    assert not any(command[:2] == ('grab', 'set') and command[-1] == '.raw.popdown'
                   for command in display.commands)


def test_valid_prior_window_grab_is_restored(display):
    host = display.Top(display.root)
    host.grab_set()
    show(display)
    assert_content_and_close(display)
    assert display.root.grab_current() is host


def test_tclerror_lookup_still_delivers_error_content(display):
    display.root.tk.fail_lookup = True
    show(display)
    assert_content_and_close(display)
    assert display.root.grab_current() is None


def test_destroyed_prior_window_is_not_regrabbed(display):
    host = display.Top(display.root)
    host.grab_set()
    show(display)
    host.destroy()
    assert_content_and_close(display)
    assert display.root.grab_current() is None


def test_newer_valid_holder_is_not_stolen_on_close(display):
    host = display.Top(display.root)
    host.grab_set()
    show(display)
    dialog = display.windows[-1]
    newer = display.Top(display.root)
    newer.grab_set()
    dialog.protocols['WM_DELETE_WINDOW']()
    assert display.root.grab_current() is newer


def test_new_tcl_only_holder_is_not_stolen_or_raised_on_close(display):
    host = display.Top(display.root)
    host.grab_set()
    show(display)
    dialog = display.windows[-1]
    display.root.tk.holder = '.raw.newer'
    dialog.protocols['WM_DELETE_WINDOW']()
    assert not dialog.alive
    assert display.root.tk.holder == '.raw.newer'


def test_close_after_parent_teardown_still_ignores_tclerror(display):
    host = display.Top(display.root)
    host.grab_set()
    show(display)
    dialog = display.windows[-1]
    host.destroy()
    def already_destroyed():
        raise tk.TclError('synthetic child already destroyed with parent')
    dialog.destroy = already_destroyed
    dialog.protocols['WM_DELETE_WINDOW']()
    assert not host.alive


def test_unexpected_grab_failure_is_not_blanket_suppressed(display):
    def unexpected():
        raise RuntimeError('synthetic unrelated programming error')
    display.root.grab_current = unexpected
    with pytest.raises(RuntimeError, match='unrelated programming error'):
        show(display)
