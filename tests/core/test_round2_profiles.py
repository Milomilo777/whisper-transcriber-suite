"""Profile spellings and concurrent task defaults, without GUI construction."""
import json
from types import SimpleNamespace

import pytest

from core import _checkpoint as cp, config as cfg, task_settings, transcriber as tr
from core.server import httpd
from tests.core.test_word_timing_profiles import profile


@pytest.mark.parametrize('saved', [False, True])
@pytest.mark.parametrize('spelling', ['missing', 'explicit', 'era'])
def test_resume_recovers_profile_checkpoint(saved, spelling):
    original = {'word_timestamps_profile_default': saved}
    data = {'config_fingerprint': cp.config_fingerprint(original), 'word_timestamps': saved}
    current = {} if spelling == 'missing' else {
        'word_timestamps' if spelling == 'explicit' else 'word_timestamps_profile_default': not saved}
    recovered = cp.config_for_resume(data, current)
    assert data['config_fingerprint'] in cp.accepted_fingerprints(recovered)


@pytest.mark.parametrize('saved', [False, True])
@pytest.mark.parametrize('explicit', [False, True])
def test_real_resume_keeps_checkpoint_and_uses_saved_value(monkeypatch, saved, explicit):
    original = {'word_timestamps_profile_default': saved}
    current = dict(original, **({'word_timestamps': not saved} if explicit else {}))
    monkeypatch.setattr(tr, 'config', current)
    monkeypatch.setattr(tr, '_apply_runtime_overrides', lambda task: {})
    monkeypatch.setattr(cfg, 'load_project_overrides', lambda path: {})
    data = {'config_fingerprint': cp.config_fingerprint(original), 'word_timestamps': saved,
            'whisper_task': 'transcribe', 'segments': [{'start': 0, 'end': 1, 'text': 'saved'}]}
    monkeypatch.setattr(cp, 'load_checkpoint', lambda path: data)
    monkeypatch.setattr(cp, 'validate_checkpoint', lambda data, **kw:
        None if data['config_fingerprint'] in kw['cfg_fingerprint'] else 'config changed')
    deleted = []
    monkeypatch.setattr(cp, 'delete_checkpoint', lambda path: deleted.append(path))
    monkeypatch.setattr(tr, '_note_run_identity', lambda task: None)
    observed = []
    class StopAfterValidation(Exception):
        pass
    def stop(*args):
        observed.append(current['word_timestamps'])
        raise StopAfterValidation
    monkeypatch.setattr(tr, '_checked_whisper_task', stop)
    before = dict(current)
    task = SimpleNamespace(file_path='saved.wav', cancelled=False, task_settings=None)
    with pytest.raises(StopAfterValidation):
        tr.resume_transcription(task)
    assert deleted == []
    assert observed == [saved]
    assert current == before


def test_false_inherited_profile_survives_save_without_disk(profile):
    profile.write_text('{"theme":"dark"}', encoding='utf-8')
    loaded = cfg.load_config(fetch_online=False)
    assert loaded['word_timestamps'] is False
    profile.unlink()
    cfg.save_config(loaded)
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is False


def test_counter_first_profile_still_shows_quick_start(profile):
    cfg.update_config(lambda data: data.update(cloud_stt_minutes_used=1))
    assert cfg.load_config(fetch_online=False)['quick_start_done'] is False


def test_api_default_does_not_observe_active_task(monkeypatch):
    monkeypatch.setattr(cfg, 'load_config', lambda **kw: {'word_timestamps': False})
    monkeypatch.setattr(tr, 'config', {'word_timestamps': False})
    monkeypatch.setattr(tr, '_apply_runtime_overrides', lambda task: {})
    monkeypatch.setattr(cfg, 'load_project_overrides', lambda path: {})
    task = SimpleNamespace(file_path='file.wav', task_settings={'word_timestamps': True})
    with tr._runtime_overrides_scope(task):
        assert tr.config['word_timestamps'] is True
        assert httpd._server_word_timestamps_default() is False
    assert tr.config['word_timestamps'] is False


def test_snapshot_skips_unserializable_word_choice():
    assert 'word_timestamps' not in task_settings.snapshot({'word_timestamps': object()})


def test_empty_snapshot_deliberately_pins_legacy_false():
    assert task_settings.snapshot({})['word_timestamps'] is False
