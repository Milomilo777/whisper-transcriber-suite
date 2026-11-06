"""Profile-era defaults, worker dispatch, API options and checkpoint compatibility."""
import json
from pathlib import Path

import pytest

from core import _checkpoint as cp, config as cfg, task_settings


def test_default_remains_off_until_gate_passes():
    assert cfg.DEFAULT_CONFIG['word_timestamps'] is False


@pytest.fixture
def profile(tmp_path, monkeypatch):
    path = tmp_path / 'config.json'
    monkeypatch.setattr(cfg, 'config_path', lambda: str(path))
    monkeypatch.setattr(cfg, 'migrate_config_location', lambda: None)
    monkeypatch.setattr(cfg, 'migrate_legacy_app_data', lambda: None)
    monkeypatch.setitem(cfg.DEFAULT_CONFIG, 'word_timestamps', True)
    cfg._forget_last_good()
    yield path
    cfg._forget_last_good()


@pytest.mark.parametrize('saved,expected', [({}, False), ({'word_timestamps': True}, True),
                                          ({'word_timestamps': False}, False)])
def test_old_profile_keeps_original_behavior(profile, saved, expected):
    profile.write_text(json.dumps({'theme': 'dark', **saved}), encoding='utf-8')
    loaded = cfg.load_config(fetch_online=False)
    assert loaded['word_timestamps'] is expected
    loaded['font_size'] = 17
    cfg.save_config(loaded)
    disk = json.loads(profile.read_text(encoding='utf-8'))
    assert ('word_timestamps' in disk) == ('word_timestamps' in saved)
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is expected


def test_fresh_profile_records_default_era_without_freezing_choice(profile, monkeypatch):
    loaded = cfg.load_config(fetch_online=False)
    assert loaded['word_timestamps'] is True
    cfg.save_config(loaded)
    disk = json.loads(profile.read_text(encoding='utf-8'))
    assert 'word_timestamps' not in disk
    monkeypatch.setitem(cfg.DEFAULT_CONFIG, 'word_timestamps', False)
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is True
    loaded['word_timestamps'] = False
    cfg.save_config(loaded)
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is False


@pytest.mark.parametrize('writer', ['save', 'update'])
def test_first_unrelated_write_records_new_profile_era(profile, writer, monkeypatch):
    if writer == 'save':
        cfg.save_config({'theme': 'dark'})
    else:
        cfg.update_config(lambda data: data.update(cloud_stt_minutes_used=1))
    disk = json.loads(profile.read_text(encoding='utf-8'))
    assert 'word_timestamps' not in disk
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is True
    monkeypatch.setitem(cfg.DEFAULT_CONFIG, 'word_timestamps', False)
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is True


def test_task_snapshot_does_not_inherit_stale_worker_words():
    assert task_settings.snapshot({})['word_timestamps'] is False


@pytest.mark.parametrize('saved', [{}, {'cloud_stt_minutes_used': 1}])
def test_any_existing_profile_without_key_keeps_off(profile, saved):
    profile.write_text(json.dumps(saved), encoding='utf-8')
    assert cfg.load_config(fetch_online=False)['word_timestamps'] is False


@pytest.mark.parametrize('original', [False, True, None])
def test_legacy_checkpoint_recovers_setting_from_fingerprint(original):
    old = {'model': 'test', 'word_timestamps': original} if original is not None else {'model': 'test'}
    data = {'config_fingerprint': cp.config_fingerprint(old)}
    current = {'model': 'test', 'word_timestamps': original is not True}
    recovered = cp.config_for_resume(data, current)
    assert cp.config_fingerprint(recovered) == data['config_fingerprint']
    assert current['word_timestamps'] is (original is not True)


def test_resume_does_not_mask_other_setting_changes():
    old = {'word_timestamps': False, 'vad_enabled': True}
    current = {'word_timestamps': True, 'vad_enabled': False}
    assert cp.config_for_resume({'config_fingerprint': cp.config_fingerprint(old)}, current) == current


def test_api_exposes_effective_default(monkeypatch):
    from core.server.httpd import JobRequestHandler
    monkeypatch.setattr(cfg, 'load_config', lambda **kw: {'word_timestamps': True})
    payload = JobRequestHandler._options_payload(object.__new__(JobRequestHandler))
    assert payload['defaults']['word_timestamps'] is True
    page = Path('core/server/static/index.html').read_text(encoding='utf-8')
    assert 'checked = wordTimestampsDefault' in page
    assert 'd.defaults.word_timestamps' in page


def test_web_does_not_submit_false_before_defaults_arrive():
    import shutil
    import subprocess

    node = shutil.which('node')
    if node is None:
        pytest.skip('Node.js is required to execute the web form')
    page = Path('core/server/static/index.html').read_text(encoding='utf-8')
    gather = page[page.index('  function gatherOptions()'):page.index('  function setSubmitStatus(')]
    script = '''const assert = require('node:assert/strict');
      var wordTimestampsLoaded = false;
      var document = {getElementById: () => ({checked: false})};
      function numOrUndef() { return undefined; }
    ''' + gather + '''
      assert.equal(Object.hasOwn(gatherOptions(), 'word_timestamps'), false);
      wordTimestampsLoaded = true;
      assert.equal(gatherOptions().word_timestamps, false);
      document.getElementById = () => ({checked: true});
      assert.equal(gatherOptions().word_timestamps, true);
    '''
    completed = subprocess.run([node, '-e', script], capture_output=True, text=True,
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    assert completed.returncode == 0, completed.stderr
