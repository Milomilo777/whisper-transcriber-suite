"""Actual close/Destroy callbacks; native WM/grab event delivery remains separate."""
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.widgets import error_dialog
from tests.core.test_error_dialog_grab_lookup import display  # noqa: F401


@pytest.fixture(params=[False, True], ids=['grab-released-after-event','grab-released-before-event'])
def lifecycle(display, monkeypatch, request):
    window_class = error_dialog.tk.Tk
    original_destroy = window_class.destroy
    def destroy(window):
        if not window.alive:
            return
        # Tk destroy removes descendants and sends Destroy notifications;
        # support both grab-release orders accepted by the project's grab.py.
        for child in list(window.children.values()):
            child.destroy()
        if request.param and window.tk.holder == window._w:
            window.tk.holder = ''
        callback = window.bindings.get('<Destroy>')
        if callback:
            callback(SimpleNamespace(widget=window))
        original_destroy(window)
    monkeypatch.setattr(window_class,'destroy',destroy)
    return display


def open_error(state, parent=None, title='Error'):
    error_dialog.show_error(parent or state.root,title,'Message')
    return state.windows[-1]


def close(dialog):
    dialog.protocols['WM_DELETE_WINDOW']()


def test_out_of_order_error_close_restores_live_original_modal(lifecycle):
    state = lifecycle
    host = state.Top(state.root)
    host.grab_set()
    first = open_error(state,title='First')
    second = open_error(state,title='Second')
    close(first)
    assert state.root.grab_current() is second
    close(second)
    assert state.root.grab_current() is host


def test_actual_viewer_close_callback_destroys_child_error_and_restores_other_modal(lifecycle):
    state = lifecycle
    host, viewer = state.Top(state.root), state.Top(state.root)
    host.grab_set()
    error = open_error(state,parent=viewer)
    # Execute the real legal viewer-close branch: no dirty edits, pending
    # completed results or playback. The native WM invocation remains untested.
    path = Path(__file__).resolve().parents[2] / 'app/dialogs/transcript_viewer.py'
    viewer_class = next(n for n in ast.parse(path.read_text(encoding='utf-8')).body
                        if isinstance(n,ast.ClassDef) and any(isinstance(f,ast.FunctionDef) and f.name=='_on_close' for f in n.body))
    function = next(n for n in viewer_class.body if isinstance(n,ast.FunctionDef) and n.name=='_on_close')
    namespace = {'_confirm_completed_results':lambda *args: True}
    code = ast.Module(body=[ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0),function],type_ignores=[])
    exec(compile(ast.fix_missing_locations(code),str(path),'exec'),namespace)
    for name in ('_vlc_bind_id','vlc_seek_after','_find_dialog','vlc_player','vlc_instance'):
        setattr(viewer,name,None)
    viewer._dirty = False
    namespace['_on_close'](viewer)
    assert not viewer.alive and not error.alive
    assert state.root.grab_current() is host


def test_in_order_closes_keep_existing_grab_restore(lifecycle):
    state = lifecycle
    host = state.Top(state.root)
    host.grab_set()
    first = open_error(state)
    second = open_error(state)
    close(second)
    assert state.root.grab_current() is first
    close(first)
    assert state.root.grab_current() is host


def test_parent_destroy_does_not_steal_newer_external_window_grab(lifecycle):
    state = lifecycle
    host, parent = state.Top(state.root), state.Top(state.root)
    host.grab_set()
    open_error(state,parent=parent)
    newer = state.Top(state.root)
    newer.grab_set()
    parent.destroy()
    assert state.root.grab_current() is newer


def test_parent_destroy_does_not_steal_newer_unwrapped_grab(lifecycle):
    state = lifecycle
    host, parent = state.Top(state.root), state.Top(state.root)
    host.grab_set()
    open_error(state,parent=parent)
    state.root.tk.holder = '.raw.newer'
    parent.destroy()
    assert state.root.tk.holder == '.raw.newer'


def test_child_destroy_notification_cannot_restore_before_error_closes(lifecycle):
    state = lifecycle
    host = state.Top(state.root)
    host.grab_set()
    error = open_error(state)
    callback = error.bindings.get('<Destroy>')
    if callback:
        callback(SimpleNamespace(widget=object()))
    assert state.root.grab_current() is error
    close(error)
    assert state.root.grab_current() is host


def test_application_teardown_never_regrabs_destroyed_host(lifecycle):
    state = lifecycle
    host, parent = state.Top(state.root), state.Top(state.root)
    host.grab_set()
    open_error(state,parent=parent)
    start = len(state.commands)
    state.root.destroy()
    assert not host.alive and not parent.alive
    assert state.root.tk.holder == ''
    assert not any(command[:2] == ('grab','set') for command in state.commands[start:])
