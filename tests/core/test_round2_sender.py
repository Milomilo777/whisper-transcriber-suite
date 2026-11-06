"""Sender findings reproduced at the privacy boundary and persistent limiter."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import traceback

import numpy as np
import pytest

from core import config, failure_clue as clue, stats


@pytest.mark.parametrize('status', ['finished', 'done'])
@pytest.mark.parametrize('recovery', ['cpu_fallback', 'cuda_batch_reduced', 'retried_ok'])
def test_recovered_success_has_version_and_run_id(status, recovery):
    context = clue.context_clue(SimpleNamespace(_telemetry_recovery=recovery), probe=False)
    row = stats.build_stats_payload(model='large-v3', language='en', audio_duration=1,
        transcription_time=1, status=status, failure_clue=context)
    assert row['classifier_version'] == '2'
    assert len(row['run_id']) == 16
    assert row['recovered'] == recovery


def test_parent_retains_registered_context():
    event = dict(progress_pct=40, elapsed_bucket='lt1m', gpu_vendor='nvidia',
        vram_bucket='4_6gb', compute_type='int8', diarization=True, vad=False,
        language_mode='auto', input_kind='file', input_container='wav',
        input_duration_bucket='lt1m', input_size_bucket='lt100mb', disk_free_bucket='more',
        ram_free_bucket='more', build_kind='source')
    row = clue.parent_clue('parent.worker_exit', exit_code=1, event=event)
    clean = clue.sanitise_clue(event)
    assert {k: row.get(k) for k in event} == {k: clean[k] for k in event}


def test_posix_abort_keeps_exact_native_allocation_evidence(monkeypatch):
    monkeypatch.setattr(clue.sys, 'platform', 'linux')
    row = clue.parent_clue('parent.worker_exit', exit_code=-6,
        event=clue.stderr_clue(["terminate called after throwing an instance of 'std::bad_alloc'",
                               '  what():  std::bad_alloc']))
    assert row['observed_code'] == 'ct2_bad_alloc'
    assert row['exit_code'] == '-6'


def test_numpy_exception_formats_like_real_subprocess_traceback():
    from numpy._core._exceptions import _ArrayMemoryError
    filename = str(Path('core/speech_collect.py').resolve())
    scope = {'error': _ArrayMemoryError((100,), np.dtype('float32'))}
    exec(compile('def gather_speech():\n    raise error\n', filename, 'exec'), scope)
    try:
        scope['gather_speech']()
    except MemoryError as error:
        lines = ''.join(traceback.format_exception(error)).splitlines()
    row = clue.stderr_clue(lines)
    assert row['exception_family'] == 'MemoryError'
    assert row['observed_code'] == 'numpy_alloc_failed'
    assert row['last_stage'] == 'vad'


def test_stderr_uses_outer_registered_site_when_inner_has_no_site():
    row = clue.stderr_clue(['Traceback (most recent call last):',
        f'  File "{Path("core/transcriber.py").resolve()}", line 100, in _write_outputs',
        f'  File "{Path("core/writers/srt.py").resolve()}", line 20, in write',
        'RuntimeError: unknown'])
    assert row['last_stage'] == 'write'


def test_repeat_count_belongs_to_fingerprint(tmp_path):
    stats._SESSION_ERRORS.clear()
    path = tmp_path / 'telemetry-errors.json'
    def admit(fp, now):
        return stats.limit_error_row(dict(status='error', fingerprint=fp), 'install', path=path, now=now)
    assert admit('a'*12, 1)['repeat_bucket'] == '0'
    for now in range(2, 6):
        assert admit('a'*12, now) is None
    distinct = admit('b'*12, 6)
    assert distinct['repeat_bucket'] == '0'
    # Session errors count occurrences, including suppressed repeats.
    assert distinct['session_error_bucket'] == '4-9'
    assert admit('a'*12, 3602)['repeat_bucket'] == '3-9'


def test_opt_out_forgets_disk_and_memory_even_without_current_id(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'config_path', lambda: str(tmp_path / 'config.json'))
    path = tmp_path / 'telemetry-errors.json'
    stats.limit_error_row(dict(status='error', fingerprint='a'*12), 'install', path=path, now=1)
    assert path.exists() and stats._SESSION_ERRORS
    cfg = {'telemetry_opt_in': False, 'install_id': ''}
    stats.forget_install_id(cfg)
    assert not path.exists()
    assert not stats._SESSION_ERRORS
    # A stable non-identifying lock must not be unlinked under another holder.
    assert path.with_suffix('.lock').read_bytes() in (b'', b'0')


def test_opt_out_during_sender_reservation_does_not_send_or_recreate_state(tmp_path, monkeypatch):
    from core import offline
    monkeypatch.setattr(config, 'config_path', lambda: str(tmp_path / 'config.json'))
    monkeypatch.setattr(config, 'effective_stats_url', lambda cfg: 'https://example.invalid/stats')
    monkeypatch.setattr(offline, 'is_offline', lambda *a: False)
    cfg = {'telemetry_opt_in': True, 'install_id': '00000000-0000-4000-8000-000000000000'}
    targets = []
    class Deferred:
        def __init__(self, target, **kwargs):
            targets.append(target)
        def start(self):
            pass
    monkeypatch.setattr(stats.threading, 'Thread', Deferred)
    posts = []
    monkeypatch.setattr(stats, '_post', lambda *a: posts.append(a))
    reserve = stats.limit_error_row
    def opt_out_then_reserve(*args, **kwargs):
        cfg['telemetry_opt_in'] = False
        stats.forget_install_id(cfg)
        return reserve(*args, **kwargs)
    monkeypatch.setattr(stats, 'limit_error_row', opt_out_then_reserve)
    assert stats.post_stats_async(cfg, {'status': 'error', 'fingerprint': 'a'*12})
    targets[0]()
    assert posts == []
    assert not (tmp_path/'telemetry-errors.json').exists()
    assert not stats._SESSION_ERRORS


def test_reenable_does_not_send_rows_queued_before_opt_out(tmp_path, monkeypatch):
    from core import offline

    monkeypatch.setattr(config, 'config_path', lambda: str(tmp_path / 'config.json'))
    monkeypatch.setattr(config, 'effective_stats_url', lambda cfg: 'https://example.invalid/stats')
    monkeypatch.setattr(offline, 'is_offline', lambda *a: False)
    previous = '00000000-0000-4000-8000-000000000000'
    current = '00000000-0000-4000-8000-000000000001'
    cfg = {'telemetry_opt_in': True, 'install_id': previous}
    targets = []
    posts = []

    class Deferred:
        def __init__(self, target, **kwargs):
            targets.append(target)

        def start(self):
            pass

    monkeypatch.setattr(stats.threading, 'Thread', Deferred)
    monkeypatch.setattr(stats, '_post', lambda _url, row, _timeout: posts.append(row))
    assert stats.post_stats_async(cfg, {'status': 'finished', 'install_id': previous})
    cfg['telemetry_opt_in'] = False
    stats.forget_install_id(cfg)
    cfg.update(telemetry_opt_in=True, install_id=current)
    assert stats.post_stats_async(cfg, {'status': 'finished', 'install_id': current})
    for send in targets:
        send()
    assert posts == [{'status': 'finished', 'install_id': current}]
