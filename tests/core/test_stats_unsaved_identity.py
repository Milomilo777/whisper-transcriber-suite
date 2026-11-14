"""A failed new identity save must not discard anonymous usage rows."""
import json
import uuid
import threading

import pytest

from core import config, offline, stats


@pytest.mark.parametrize('save_fails', [True, False])
def test_concurrent_pending_identity_retains_both_usage_rows(tmp_path, monkeypatch, save_fails):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'telemetry_opt_in': True}), encoding='utf-8')
    monkeypatch.setattr(config, 'config_path', lambda: str(path))
    monkeypatch.setattr(offline, 'is_offline', lambda: False)
    entered, release = threading.Event(), threading.Event()
    failures, identities, posted, senders = [], {}, [], []
    cfg = {'telemetry_opt_in': True, 'stats_url': 'https://example.invalid/stats'}

    def blocked_save(value):
        entered.set()
        if not release.wait(3):
            failures.append('pending identity save barrier timed out')
            raise AssertionError(failures[-1])
        if save_fails:
            raise OSError('synthetic failed pending identity save')
        path.write_text(json.dumps(value), encoding='utf-8')

    def send(name):
        try:
            identities[name] = stats.install_id_for(cfg)
            row = stats.build_stats_payload(model='tiny', language='en', audio_duration=1,
                                            transcription_time=1, status='finished',
                                            install_id=identities[name])
            assert stats.post_stats_async(cfg, row)
        except BaseException as error:
            failures.append(error)

    class Deferred:
        def __init__(self, target, args=(), **_kwargs):
            senders.append(lambda: target(*args))
        def start(self):
            pass

    first = threading.Thread(target=send, args=('A',), name='pending-id-first')
    monkeypatch.setattr(config, 'save_config', blocked_save)
    monkeypatch.setattr(stats.threading, 'Thread', Deferred)
    monkeypatch.setattr(stats, '_post', lambda _url, row, _timeout: posted.append(dict(row)))
    first.start()
    try:
        assert entered.wait(2), 'first caller did not enter identity persistence'
        send('B')
        assert first.is_alive(), 'second caller waited for pending identity persistence'
    finally:
        release.set()
        first.join(3)
    assert not first.is_alive()
    assert failures == []
    assert id(cfg) not in stats._PENDING_INSTALL_IDS
    assert identities['B'] == '', 'a caller observed the identity before its save completed'
    assert len(senders) == 2
    for sender in senders:
        sender()
    assert len(posted) == 2, 'failed pending identity discarded one caller\'s finished usage'
    if save_fails:
        assert all('install_id' not in row for row in posted)
        assert not cfg.get('install_id')
    else:
        assert identities['A'] == cfg['install_id']
        assert any(row.get('install_id') == cfg['install_id'] for row in posted)


def test_failed_new_identity_save_preserves_anonymous_usage(tmp_path, monkeypatch):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"telemetry_opt_in": True}), encoding="utf-8")
    monkeypatch.setattr(config, "config_path", lambda: str(path))
    monkeypatch.setattr(offline, "is_offline", lambda: False)
    posted = []

    def fail_save(_value):
        raise OSError("synthetic read-only preferences")

    class Immediate:
        def __init__(self, target, args=(), **_kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(config, "save_config", fail_save)
    monkeypatch.setattr(stats.threading, "Thread", Immediate)
    monkeypatch.setattr(stats, "_post", lambda _url, row, _timeout: posted.append(dict(row)))
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/stats"}
    for _ in range(2):
        identity = stats.install_id_for(cfg)
        row = stats.build_stats_payload(model="tiny", language="en", audio_duration=1,
                                        transcription_time=1, status="finished", install_id=identity)
        assert stats.post_stats_async(cfg, row)
    assert len(posted) == 2, "failed identity persistence discarded finished usage"
    assert all("install_id" not in row for row in posted)
    assert not cfg.get("install_id"), "an unpersisted candidate was cached for later identified sends"


def test_failed_new_identity_save_does_not_clear_a_replaced_identity(monkeypatch):
    newer = str(uuid.uuid4())
    cfg = {"telemetry_opt_in": True}

    def replace_then_fail(_value):
        cfg["install_id"] = newer
        raise OSError("synthetic save failure")

    monkeypatch.setattr(config, "save_config", replace_then_fail)
    assert stats.install_id_for(cfg) == ""
    assert cfg["install_id"] == newer


def test_failed_new_identity_save_does_not_restore_revoked_candidate(monkeypatch):
    cfg = {"telemetry_opt_in": True}

    def revoke_then_fail(_value):
        cfg["telemetry_opt_in"] = False
        cfg["install_id"] = ""
        raise OSError("synthetic save failure after revocation")

    monkeypatch.setattr(config, "save_config", revoke_then_fail)
    assert stats.install_id_for(cfg) == ""
    assert cfg == {"telemetry_opt_in": False, "install_id": ""}
