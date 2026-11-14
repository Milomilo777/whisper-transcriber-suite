"""Real stop/controller methods with owned WAVs and bounded fake scheduling."""
import ast
import logging
from pathlib import Path
from types import ModuleType, SimpleNamespace
import sys

import _tkinter
import pytest

from core.recorder import Recorder


class Capture:
    alive = True

    def __init__(self):
        self.joins = []

    def is_alive(self): return self.alive
    def join(self, timeout=None): self.joins.append(timeout)


@pytest.fixture
def recording(tmp_path, monkeypatch):
    path = tmp_path / 'partial.wav'
    recorder = Recorder(str(path))
    with recorder._open_wave(16000) as stream:
        stream.writeframes(b'\x01\x00' * 64000)
    capture = Capture()
    recorder._thread = capture
    aborts = []
    recorder._stream = SimpleNamespace(abort=lambda: aborts.append(True))
    monkeypatch.setattr(recorder, '_finalize_wav', lambda: pytest.fail('Partial audio must never be truncated'))
    return SimpleNamespace(recorder=recorder, capture=capture, aborts=aborts,
                           path=path, original=path.read_bytes())


@pytest.mark.parametrize('first_error', [None, 'original device error'])
def test_stop_marks_unfinished_capture_and_preserves_first_error_and_bytes(recording, first_error):
    recorder = recording.recorder
    recorder.last_error = first_error
    assert recorder.stop(timeout=0.01) == str(recording.path)
    assert recorder.is_running()
    assert recorder.last_error and (recorder.last_error == first_error if first_error else 'incomplete' in recorder.last_error)
    assert recording.path.read_bytes() == recording.original
    assert recording.aborts == [True] and len(recording.capture.joins) == 2


class Widget:
    def __init__(self): self.state = 'disabled'
    def configure(self, **kwargs): self.state = kwargs.get('state', self.state)


@pytest.fixture
def controller(recording, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Controller tests must not construct Tk')
    monkeypatch.setattr(_tkinter, 'create', forbidden)
    voice = ModuleType('core.voice_clone')
    voice.MAX_REFERENCE_SAMPLES = 3
    monkeypatch.setitem(sys.modules, 'core.voice_clone', voice)
    monkeypatch.setattr('core.recorder.mic_available', forbidden)
    callbacks, cancelled, errors, added, statuses = {}, [], [], [], []
    serial = []

    def after(milliseconds, callback):
        serial.append(milliseconds)
        identifier = f'after-{len(serial)}'
        callbacks[identifier] = callback
        return identifier

    def cancel(identifier):
        cancelled.append(identifier)
        callbacks.pop(identifier, None)

    app = SimpleNamespace(vc_recorder=recording.recorder, vc_recording_after_id=None,
        vc_recording_stopping=False, vc_worker=None, vc_cancel_event=None,
        vc_busy=False, vc_confirm_open=False, vc_load_btn=Widget(), vc_remove_btn=Widget(),
        vc_consent_check=Widget(), vc_mode_radios=[], vc_design_widgets=[],
        vc_voice_combo=Widget(), vc_lang_combo=Widget(), vc_record_btn=Widget(),
        vc_status_var=SimpleNamespace(set=statuses.append), after=after, after_cancel=cancel)
    namespace = {'logger': logging.getLogger(__name__), 'os': __import__('os'),
        '_': lambda text, **kwargs: text.format(**kwargs),
        'show_error': lambda *args, **kwargs: errors.append((args, kwargs)),
        '_validate_and_add_sample': lambda app, path: added.append(path),
        'ttk': SimpleNamespace(Combobox=type('Combobox', (), {})), '_is_kokoro': lambda app: False}
    source = Path(__file__).resolve().parents[1] / 'app/widgets/voice_clone_tab.py'
    tree = ast.parse(source.read_text(encoding='utf-8'))
    names = {'_finish_recording', '_poll_recording_stop', 'stop_voice_clone_worker',
             '_sync_lock', '_record_sample', '_tick_recording'}
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *selected], type_ignores=[])), str(source), 'exec'), namespace)
    stops = []
    actual_stop = recording.recorder.stop

    def stop():
        stops.append(True)
        return actual_stop(timeout=0.01)

    monkeypatch.setattr(recording.recorder, 'stop', stop)
    return SimpleNamespace(app=app, callbacks=callbacks, cancelled=cancelled, errors=errors,
        added=added, statuses=statuses, delays=serial, stops=stops, namespace=namespace,
        call=lambda name: namespace[name](app))


def test_supported_finish_retains_capture_and_polls_without_repeated_stop(recording, controller):
    controller.call('_finish_recording')
    assert controller.app.vc_recorder is recording.recorder
    assert controller.app.vc_record_btn.state == 'disabled'
    assert not controller.added and len(controller.errors) == 1
    assert str(recording.path) in controller.errors[0][1]['detail']
    assert controller.app.vc_recording_after_id in controller.callbacks
    for _ in range(3):
        identifier = controller.app.vc_recording_after_id
        controller.callbacks.pop(identifier)()
    controller.call('_finish_recording')
    assert controller.stops == [True] and len(recording.capture.joins) == 2
    assert len(controller.errors) == 1 and not controller.added
    assert recording.path.read_bytes() == recording.original


def test_late_exit_releases_lock_without_adding_partial_or_calling_stop(recording, controller):
    controller.call('_finish_recording')
    recording.capture.alive = False
    controller.callbacks.pop(controller.app.vc_recording_after_id)()
    assert controller.app.vc_recorder is None
    assert not controller.app.vc_recording_stopping
    assert controller.app.vc_recording_after_id is None
    assert controller.app.vc_record_btn.state == 'normal'
    assert controller.statuses[-1] == 'Idle.'
    assert not controller.added and controller.stops == [True]
    assert recording.path.read_bytes() == recording.original


@pytest.mark.parametrize('busy,confirm', [(False, False), (True, False), (False, True)])
def test_healthy_completed_clip_keeps_existing_validation_and_job_lock(recording, controller, busy, confirm):
    recording.capture.alive = False
    controller.app.vc_busy, controller.app.vc_confirm_open = busy, confirm
    controller.call('_finish_recording')
    assert controller.app.vc_recorder is None
    assert controller.added == [str(recording.path)] and not controller.errors
    assert not controller.callbacks
    assert controller.app.vc_record_btn.state == ('disabled' if busy or confirm else 'normal')
    assert recording.path.read_bytes() == recording.original


def test_teardown_cancels_pending_poll_and_retains_active_file_owner(recording, controller):
    controller.call('_finish_recording')
    identifier = controller.app.vc_recording_after_id
    stale_callback = controller.callbacks[identifier]
    controller.call('stop_voice_clone_worker')
    assert controller.cancelled == [identifier] and not controller.callbacks
    assert controller.app.vc_recording_after_id is None
    assert controller.app.vc_recorder is recording.recorder
    assert controller.stops == [True]
    stale_callback()
    assert not controller.callbacks and controller.app.vc_recorder is recording.recorder
    recording.capture.alive = False
    controller.call('stop_voice_clone_worker')
    assert controller.app.vc_recorder is None and controller.stops == [True]
    assert recording.path.read_bytes() == recording.original


def test_record_action_cannot_replace_a_retained_capture_owner(recording, controller):
    controller.call('_finish_recording')
    controller.call('_record_sample')
    assert controller.app.vc_recorder is recording.recorder
    assert controller.stops == [True] and not controller.added


def test_close_during_countdown_cancels_timer_without_rescheduling(recording, controller):
    controller.namespace['_tick_recording'](controller.app, 1)
    identifier = controller.app.vc_recording_after_id
    stale_tick = controller.callbacks[identifier]
    controller.call('stop_voice_clone_worker')
    stale_tick()
    assert not controller.callbacks and controller.app.vc_recording_after_id is None
    assert controller.app.vc_recorder is recording.recorder
    assert controller.stops == [True]
    assert recording.path.read_bytes() == recording.original


def test_live_capture_is_not_validated_even_without_stop_error_signal(recording, controller, monkeypatch):
    monkeypatch.setattr(recording.recorder, 'stop', lambda: str(recording.path))
    controller.call('_finish_recording')
    assert controller.app.vc_recorder is recording.recorder
    assert not controller.added
    assert controller.app.vc_recording_after_id in controller.callbacks


def test_raised_stop_keeps_owner_until_exit_without_retrying_native_stop(recording, controller, monkeypatch):
    attempts = []

    def failed_stop():
        attempts.append(True)
        raise OSError('synthetic native stop failure')

    monkeypatch.setattr(recording.recorder, 'stop', failed_stop)
    controller.call('_finish_recording')
    assert controller.app.vc_recorder is recording.recorder
    assert len(controller.errors) == 1 and not controller.added
    recording.capture.alive = False
    controller.callbacks.pop(controller.app.vc_recording_after_id)()
    assert controller.app.vc_recorder is None and attempts == [True]
    assert recording.path.read_bytes() == recording.original


def test_stale_poll_cannot_release_a_new_owner_or_its_callback(recording, controller):
    controller.call('_finish_recording')
    callback = controller.callbacks.pop(controller.app.vc_recording_after_id)
    new_owner = object()
    controller.app.vc_recorder = new_owner
    controller.app.vc_recording_after_id = 'new-owner-timer'
    callback()
    assert controller.app.vc_recorder is new_owner
    assert controller.app.vc_recording_after_id == 'new-owner-timer'


@pytest.mark.parametrize('busy,confirm', [(True, False), (False, True)])
def test_late_exit_preserves_active_job_status_and_lock(recording, controller, busy, confirm):
    controller.call('_finish_recording')
    controller.app.vc_busy, controller.app.vc_confirm_open = busy, confirm
    job_status = 'Generating piece 2' if busy else 'Confirm planned job'
    controller.app.vc_status_var.set(job_status)
    recording.capture.alive = False
    controller.callbacks.pop(controller.app.vc_recording_after_id)()
    assert controller.app.vc_recorder is None and not controller.app.vc_recording_stopping
    assert controller.app.vc_record_btn.state == 'disabled'
    assert controller.statuses[-1] == job_status
    assert not controller.added and controller.stops == [True]
    assert recording.path.read_bytes() == recording.original


@pytest.mark.parametrize('exists', [True, False])
def test_pending_stop_uses_existing_localized_body_and_diagnostic_detail(recording, controller, exists):
    if not exists:
        recording.path.unlink()  # Owned synthetic fixture only.
    messages = {
        'Recording failed': 'localized failure', 'Stopping...': 'localized stopping',
        'The recording file was kept at:\n{path}\nIt may be incomplete.': 'localized retained file: {path}',
    }
    controller.namespace['_'] = lambda text, **kwargs: messages.get(text, text).format(**kwargs)
    controller.call('_finish_recording')
    args, kwargs = controller.errors[0]
    assert args[1] == 'localized failure'
    assert args[2] == 'localized stopping'
    assert recording.recorder.last_error not in args[2]
    assert recording.recorder.last_error in kwargs['detail']
    assert ('localized retained file' in kwargs['detail']) is exists
    assert controller.statuses[-1] == 'localized stopping'
    assert controller.app.vc_recorder is recording.recorder and not controller.added


@pytest.mark.parametrize('busy,confirm', [(True, False), (False, True)])
def test_pending_stop_preserves_existing_job_status(recording, controller, busy, confirm):
    controller.app.vc_busy, controller.app.vc_confirm_open = busy, confirm
    controller.app.vc_status_var.set('Current job status')
    controller.call('_finish_recording')
    assert controller.statuses[-1] == 'Current job status'
    assert controller.errors[0][0][2] == 'Recording failed'
    assert recording.recorder.last_error in controller.errors[0][1]['detail']
    assert controller.app.vc_record_btn.state == 'disabled'
    assert controller.app.vc_recorder is recording.recorder and not controller.added
