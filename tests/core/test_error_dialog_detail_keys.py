"""Actual handlers with documented bindtag ordering, not native key delivery."""
from types import SimpleNamespace

import pytest

from app.widgets import error_dialog
from tests.core.test_error_dialog_grab_lookup import display, show  # noqa: F401


@pytest.fixture
def keys(display, monkeypatch):
    widget_class = error_dialog.ttk.Button
    def bind(widget, sequence, callback, **kwargs):
        if not hasattr(widget, 'bindings'):
            widget.bindings = {}
        widget.bindings[sequence] = callback
    def invoke(widget):
        widget.invocations = getattr(widget, 'invocations', 0) + 1
        return widget.options['command']()
    monkeypatch.setattr(widget_class, 'bind', bind, raising=False)
    monkeypatch.setattr(widget_class, 'invoke', invoke, raising=False)

    def deliver(widget, sequence, *, class_invokes=False):
        # Tk bind manual: widget, class, toplevel, all. A widget result
        # "break" stops later tags. No Tcl interpreter or event is created.
        event = SimpleNamespace(widget=widget)
        callback = getattr(widget, 'bindings', {}).get(sequence)
        if callback and callback(event) == 'break':
            return 'break'
        if class_invokes:
            widget.invoke()
        dialog = display.windows[-1]
        callback = dialog.bindings.get(sequence)
        return callback(event) if callback else None

    display.deliver = deliver
    return display


@pytest.mark.parametrize('sequence', ['<Return>', '<KP_Enter>'])
@pytest.mark.parametrize('class_invokes', [False, True])
@pytest.mark.parametrize('label', ['Copy details', 'Show details ▸'])
def test_enter_invokes_focused_detail_button_without_closing(keys, sequence, class_invokes, label):
    show(keys)
    dialog = keys.windows[-1]
    button = next(w for w in keys.widgets if w.options.get('text') == label)
    result = keys.deliver(button, sequence, class_invokes=class_invokes)
    assert dialog.alive
    assert getattr(button, 'invocations', 0) == 1, 'focused action missing or invoked again'
    if label == 'Copy details':
        assert keys.clipboard == 'diagnostic detail'
    else:
        assert button.options['text'] == 'Hide details ▾'
        keys.deliver(button, sequence, class_invokes=class_invokes)
        assert button.options['text'] == 'Show details ▸'
        assert dialog.alive and button.invocations == 2
    assert result == 'break', 'later class/toplevel tags were not stopped'


def test_return_on_default_ok_still_closes(keys):
    show(keys)
    dialog = keys.windows[-1]
    ok = next(w for w in keys.widgets if w.options.get('text') == 'OK')
    keys.deliver(ok, '<Return>')
    assert not dialog.alive


def test_return_without_details_still_closes_default_dialog(keys):
    error_dialog.show_error(keys.root, 'Ordinary error', 'Message')
    dialog = keys.windows[-1]
    ok = next(w for w in keys.widgets if w.options.get('text') == 'OK')
    keys.deliver(ok, '<Return>')
    assert not dialog.alive
