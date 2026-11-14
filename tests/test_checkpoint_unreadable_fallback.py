"""Actual worker resume/fresh dispatch with real checkpoint files and no ASR."""
import ast
import builtins
from contextlib import nullcontext
import logging
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from core import _checkpoint as cp
from core.task import TranscriptionTask

ROOT = Path(__file__).resolve().parents[1]
SAVED_TEXT = 'IRREPLACEABLE HOURS OF ORIGINAL WORDS'


def write_checkpoint(source, text=SAVED_TEXT):
    return cp.write_checkpoint(str(source), backend='test_offline', model_name='test',
        language='en', language_probability=1.0, cfg_fingerprint='test',
        last_end_time=3600.0, checkpoint_time=1000.0,
        segments=[{'start': 0.0, 'end': 3600.0, 'text': text}])


@pytest.fixture
def route(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, 'user_data_dir', lambda: tmp_path / 'profile')
    monkeypatch.setattr(cp, '_RUN_IDENTITY', {})
    source = tmp_path / 'audio.wav'
    source.write_bytes(b'owned media identity fixture')
    checkpoint = write_checkpoint(source)
    started, outputs, logs = [], [], []

    def backend(_name, task, *_args):
        # A deterministic backend emits a fresh result. Actual atomic checkpoint
        # publication and success cleanup exercise the destructive fallback.
        started.append(True)
        write_checkpoint(source, 'fresh replacement words')
        output = tmp_path / 'fresh-result.txt'
        output.write_text('fresh replacement words', encoding='utf-8')
        outputs.append(output)
        cp.delete_checkpoint(str(source))

    config = {'transcribe_backend': 'test_offline'}
    namespace = {'_checkpoint': cp, 'config': config, 'logger': logging.getLogger(__name__),
        '_remember_task_device': lambda *a, **k: None, '_clue_phase': lambda *a: None,
        '_with_task_prefix': lambda callback, task: callback,
        '_runtime_overrides_scope': lambda task: nullcontext(config),
        '_clip_timestamps_arg': lambda task: None,
        'JobProgress': lambda callback, **kwargs: SimpleNamespace(transcription=callback),
        '_checked_whisper_task': lambda *a: None, '_transcribe_via_alt_backend': backend,
        'log': lambda message, callback=None: logs.append(message), 'keep_awake': nullcontext}
    tree = ast.parse((ROOT / 'core/transcriber.py').read_text(encoding='utf-8'))
    names = {'resume_transcription', 'transcribe', '_protect_existing_checkpoint',
             '_keep_checkpoint_aside', '_note_run_identity'}
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    assert len(functions) == len(names)
    # Execute the actual worker's fallback branch, not a handwritten substitute.
    worker = ast.parse((ROOT / 'core/worker.py').read_text(encoding='utf-8'))
    branches = [node for node in ast.walk(worker) if isinstance(node, ast.With)
                and any(isinstance(item.context_expr, ast.Call)
                        and getattr(item.context_expr.func, 'id', None) == 'keep_awake'
                        for item in node.items)
                and any(isinstance(child, ast.Assign) and any(
                    isinstance(target, ast.Name) and target.id == 'did_resume' for target in child.targets)
                    for child in node.body)]
    assert len(branches) == 1
    dispatch = ast.parse('def dispatch(task, progress_cb=None, log_cb=None, language_cb=None):\n    pass\n').body[0]
    dispatch.body = [branches[0]]
    future = ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[future, *functions, dispatch], type_ignores=[])),
                 '<actual-worker-and-transcriber-routes>', 'exec'), namespace)
    task = TranscriptionTask(str(source))
    task.resume = True
    return SimpleNamespace(source=source, checkpoint=checkpoint, started=started, outputs=outputs,
        logs=logs, task=task, namespace=namespace, run=lambda: namespace['dispatch'](task),
        kept=lambda: sorted(checkpoint.parent.glob(checkpoint.name + '.unverified-*')))


@pytest.mark.parametrize('damage', ['malformed-json', 'invalid-utf8', 'non-dict', 'one-read-permission-error'])
def test_supported_resume_fallback_preserves_unreadable_checkpoint_before_fresh_cleanup(route, monkeypatch, damage):
    if damage == 'malformed-json':
        route.checkpoint.write_bytes(b'{"segments":[{"text":"' + SAVED_TEXT.encode() + b'"}]')
    elif damage == 'invalid-utf8':
        route.checkpoint.write_bytes(b'{"segments":[{"text":"' + SAVED_TEXT.encode() + b'\xff"}]}')
    elif damage == 'non-dict':
        route.checkpoint.write_bytes(b'[{"text":"' + SAVED_TEXT.encode() + b'"}]')
    original = route.checkpoint.read_bytes()
    if damage == 'one-read-permission-error':
        real_open = builtins.open
        attempts = []

        def fail_once(path, *args, **kwargs):
            if os.fspath(path) == str(route.checkpoint):
                attempts.append(True)
                if len(attempts) == 1:
                    raise PermissionError('synthetic one-time checkpoint read failure')
            return real_open(path, *args, **kwargs)

        monkeypatch.setattr(builtins, 'open', fail_once)
    route.run()
    assert route.started == [True] and len(route.outputs) == 1
    assert not route.checkpoint.exists()  # Fresh success cleanup really ran.
    kept = route.kept()
    assert len(kept) == 1, 'Fresh fallback erased the unreadable resume checkpoint without retaining its bytes'
    assert kept[0].read_bytes() == original


@pytest.mark.parametrize('read_failure', ['persistent', 'once'])
def test_supported_fallback_stops_when_unreadable_checkpoint_cannot_be_kept(route, monkeypatch, read_failure):
    original = route.checkpoint.read_bytes()
    real_open = builtins.open
    attempts = []

    def deny_read(path, *args, **kwargs):
        if os.fspath(path) == str(route.checkpoint):
            attempts.append(True)
            if read_failure == 'persistent' or len(attempts) == 1:
                raise PermissionError('synthetic checkpoint read failure')
        return real_open(path, *args, **kwargs)

    def deny_rename(*args):
        raise PermissionError('synthetic checkpoint rename failure')

    def fail_copy_sync(*args):
        raise OSError('synthetic recovery-copy sync failure')

    monkeypatch.setattr(builtins, 'open', deny_read)
    monkeypatch.setattr(cp.os, 'rename', deny_rename)
    monkeypatch.setattr(cp, '_strict_sync', fail_copy_sync)
    with pytest.raises(cp.CheckpointNotKeptError):
        route.run()
    assert not route.started and not route.outputs and not route.kept()
    assert route.checkpoint.read_bytes() == original


def test_missing_checkpoint_still_allows_normal_fresh_dispatch(route):
    route.checkpoint.unlink()  # Owned fixture, not a retained recording/checkpoint.
    route.run()
    assert route.started == [True] and len(route.outputs) == 1
    assert not route.checkpoint.exists() and not route.kept()
