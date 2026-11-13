"""Argon03 claims: deterministic opt-out races, without real network traffic."""
import threading
import uuid
import json

import pytest
from core import config as config_module, diagnostic, offline, stats

REAL_SAVE_CONFIG = config_module.save_config


@pytest.fixture(autouse=True)
def isolated_stats(tmp_path, monkeypatch):
    monkeypatch.setattr(config_module, "config_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(stats, "_error_rate_path", lambda: tmp_path / "telemetry-errors.json")
    monkeypatch.setattr(diagnostic, "log_path", lambda: tmp_path / "diagnostic.log")
    monkeypatch.setattr(offline, "is_offline", lambda: False)
    monkeypatch.setattr(config_module, "save_config", lambda cfg: None)
    yield
    assert stats._ERASURE_DONE.wait(3)


def test_install_id_mint_cannot_survive_completed_opt_out(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original_uuid4 = uuid.uuid4
    saved = []
    cfg = {"telemetry_opt_in": True, "install_id": ""}

    def paused_uuid4():
        if threading.current_thread().name == "argon-install-id":
            entered.set()
            assert release.wait(3)
        return original_uuid4()

    monkeypatch.setattr(stats.uuid, "uuid4", paused_uuid4)
    monkeypatch.setattr(config_module, "save_config", lambda value: saved.append(dict(value)))
    thread = threading.Thread(target=stats.install_id_for, args=(cfg,), name="argon-install-id")
    thread.start()
    try:
        assert entered.wait(2)
        cfg["telemetry_opt_in"] = False
        stats.forget_install_id(cfg)
        assert stats._ERASURE_DONE.wait(2)
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert cfg["install_id"] == "", "a revoked mint repopulated the opted-out configuration"
    assert not any(not row["telemetry_opt_in"] and row["install_id"] for row in saved)


def test_payload_from_revoked_install_is_not_sent_after_reenable(monkeypatch):
    cfg = {"telemetry_opt_in": True}
    old = stats.install_id_for(cfg)
    payload = stats.build_stats_payload(model="tiny", language="en", audio_duration=1.,
                                        transcription_time=1., status="finished", install_id=old)
    cfg["telemetry_opt_in"] = False
    stats.forget_install_id(cfg)
    assert stats._ERASURE_DONE.wait(2)
    cfg["telemetry_opt_in"] = True
    new = stats.install_id_for(cfg)
    assert new and new != old
    cfg["stats_url"] = "https://example.invalid/stats"
    posted = []
    monkeypatch.setattr(stats, "_saved_consent_allows", lambda path: True)
    monkeypatch.setattr(stats, "_post", lambda url, row, timeout: posted.append(dict(row)))

    class ImmediateThread:
        def __init__(self, target, args=(), **kwargs):
            self.target, self.args = target, args

        def start(self):
            self.target(*self.args)

    monkeypatch.setattr(stats.threading, "Thread", ImmediateThread)
    stats.post_stats_async(cfg, payload)
    assert posted == [], "a revoked installation ID was transmitted after re-enabling telemetry"


def test_opt_out_cleanup_orders_after_an_already_admitted_disk_save(tmp_path, monkeypatch):
    entered, release = threading.Event(), threading.Event()
    original_write = config_module._write_disk_dict
    cfg = {"telemetry_opt_in": True, "install_id": ""}

    def paused_write(path, value):
        if value.get("install_id"):
            entered.set()
            assert release.wait(3)
        original_write(path, value)

    monkeypatch.setattr(config_module, "save_config", REAL_SAVE_CONFIG)
    monkeypatch.setattr(config_module, "_write_disk_dict", paused_write)
    thread = threading.Thread(target=stats.install_id_for, args=(cfg,))
    thread.start()
    try:
        assert entered.wait(2)
        cfg["telemetry_opt_in"] = False
        stats.forget_install_id(cfg)
        # Revocation stays responsive, but completion cannot precede a write
        # already holding the config storage lock.
        completed_too_early = stats._ERASURE_DONE.wait(0.1)
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert stats._ERASURE_DONE.wait(3)
    saved = json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))
    assert not saved.get("install_id"), "an admitted disk write resurrected the revoked ID"
    assert not completed_too_early


def test_two_mints_publish_one_identity(monkeypatch):
    entered = threading.Barrier(2)
    original = uuid.uuid4
    results, saved = [], []
    cfg = {"telemetry_opt_in": True, "install_id": ""}

    def together():
        entered.wait(3)
        return original()

    monkeypatch.setattr(stats.uuid, "uuid4", together)
    monkeypatch.setattr(config_module, "save_config", lambda value: saved.append(dict(value)))
    threads = [threading.Thread(target=lambda: results.append(stats.install_id_for(cfg))) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(4)
        assert not thread.is_alive()
    assert len(results) == 2 and results[0] == results[1] == cfg["install_id"]
    assert len(saved) == 1


@pytest.mark.parametrize("identity", ["", "invalid", str(uuid.uuid4())], ids=["empty", "invalid", "mismatched"])
def test_sender_rejects_mismatched_or_invalid_identified_rows(monkeypatch, identity):
    pending, posted = [], []
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/stats",
           "install_id": str(uuid.uuid4())}

    class Deferred:
        def __init__(self, target, **kwargs):
            pending.append(target)

        def start(self):
            pass

    monkeypatch.setattr(stats.threading, "Thread", Deferred)
    monkeypatch.setattr(stats, "_saved_consent_allows", lambda path: True)
    monkeypatch.setattr(stats, "_post", lambda *args: posted.append(args))
    row = {"status": "finished", "install_id": identity}
    assert stats.post_stats_async(cfg, row)
    # The producer may reuse/mutate its dictionary while delivery is queued.
    row["install_id"] = cfg["install_id"]
    pending[0]()
    assert posted == []


def test_saved_identity_erasure_preserves_new_identity_and_other_settings(tmp_path):
    path = tmp_path / "config.json"
    old, new = str(uuid.uuid4()), str(uuid.uuid4())
    path.write_text(json.dumps({"install_id": new, "theme": "dark"}), encoding="utf-8")
    stats._erase_saved_install_ids(path, {old})
    assert json.loads(path.read_text(encoding="utf-8")) == {"install_id": new, "theme": "dark"}
    stats._erase_saved_install_ids(path, {new})
    assert json.loads(path.read_text(encoding="utf-8")) == {"install_id": "", "theme": "dark"}


def test_direct_sender_cannot_bypass_model_path_privacy(monkeypatch):
    posted = []
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.invalid/stats"}

    class Immediate:
        def __init__(self, target, **kwargs):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(stats.threading, "Thread", Immediate)
    monkeypatch.setattr(stats, "_saved_consent_allows", lambda path: True)
    monkeypatch.setattr(stats, "_post", lambda url, row, timeout: posted.append(dict(row)))
    assert stats.post_stats_async(cfg, {"status": "finished", "model": "/home/private/model"})
    assert posted and posted[0]["model"] == stats.LOCAL_MODEL_LABEL


def test_old_mint_cannot_replace_the_new_identity_after_an_off_on_cycle(monkeypatch):
    entered,release=threading.Event(),threading.Event()
    original=uuid.uuid4
    cfg={"telemetry_opt_in":True,"install_id":""}
    results=[]

    def paused():
        if threading.current_thread().name=='old-mint':
            entered.set()
            assert release.wait(3)
        return original()

    monkeypatch.setattr(stats.uuid,'uuid4',paused)
    thread=threading.Thread(target=lambda:results.append(stats.install_id_for(cfg)),name='old-mint')
    thread.start()
    try:
        assert entered.wait(2)
        cfg['telemetry_opt_in']=False
        stats.forget_install_id(cfg)
        assert stats._ERASURE_DONE.wait(2)
        cfg['telemetry_opt_in']=True
        new=stats.install_id_for(cfg)
    finally:
        release.set()
        thread.join(3)
    assert not thread.is_alive()
    assert results==['']
    assert cfg['install_id']==new and new


def test_revoked_error_payload_cannot_reserve_quota(monkeypatch):
    cfg={"telemetry_opt_in":True,"stats_url":"https://example.invalid/stats"}
    old=stats.install_id_for(cfg)
    row=stats.build_stats_payload(model='tiny',language='en',audio_duration=0,
        transcription_time=0,status='error',install_id=old)
    cfg['telemetry_opt_in']=False
    stats.forget_install_id(cfg)
    assert stats._ERASURE_DONE.wait(2)
    cfg['telemetry_opt_in']=True
    assert stats.install_id_for(cfg)!=old
    calls=[]

    class Immediate:
        def __init__(self,target,**kwargs):self.target=target
        def start(self):self.target()

    monkeypatch.setattr(stats.threading,'Thread',Immediate)
    monkeypatch.setattr(stats,'_saved_consent_allows',lambda path:True)
    monkeypatch.setattr(stats,'limit_error_row',lambda *args:calls.append('reserved') or args[0])
    monkeypatch.setattr(stats,'_post',lambda *args:calls.append('posted'))
    assert stats.post_stats_async(cfg,row)
    assert calls==[]
