"""Pre-rebrand settings migration must retain saved privacy decisions on failure."""
import errno
import json
from pathlib import Path

import pytest

from core import config as cfg, hub, offline


@pytest.fixture
def profile(tmp_path, monkeypatch):
    old = {key: tmp_path / ("old-" + key) for key in ("config", "data", "cache")}
    new = {key: tmp_path / ("new-" + key) for key in ("config", "data", "cache", "log")}
    for folder in [*old.values(), *new.values()]:
        folder.mkdir()
    source = old["config"] / "config.json"
    target = new["config"] / "config.json"
    settings = {"theme": "dark", "work_offline": True,
                "telemetry_opt_in": False, "update_check_enabled": False}
    source.write_text(json.dumps(settings), encoding="utf-8")
    for key, folder in new.items():
        monkeypatch.setattr(cfg, "user_" + key + "_dir", lambda folder=folder: folder)
    monkeypatch.setattr(cfg, "config_path", lambda: str(target))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "absent-source-config.json"))
    monkeypatch.setattr(cfg, "_legacy_app_dirs", lambda: old)
    monkeypatch.setattr(cfg, "_profile_root", lambda: None)
    monkeypatch.setattr(cfg, "_legacy_migration_done", False)
    monkeypatch.setattr(cfg, "_ONLINE_MEMO", {})
    monkeypatch.setattr(hub, "default_hub_folder", lambda: new["cache"] / "models")
    monkeypatch.setattr(offline, "_override", None)
    monkeypatch.setattr(offline, "_cache_key", None)
    monkeypatch.setattr(offline, "_last_saved", False)
    cfg._forget_last_good()
    yield source, target, settings, old
    cfg._forget_last_good()


def deny_settings_copy(monkeypatch, source, partial=False):
    copy = cfg.shutil.copy2

    def fail(src, destination, *args, **kwargs):
        if Path(src) == source:
            if partial:
                Path(destination).write_bytes(b'{"theme":')
            raise OSError(errno.ENOSPC, "synthetic pre-rebrand settings failure")
        return copy(src, destination, *args, **kwargs)

    monkeypatch.setattr(cfg.shutil, "copy2", fail)


@pytest.mark.parametrize("partial", [False, True])
def test_failed_profile_transfer_retains_offline_and_optout(profile, monkeypatch, partial):
    source, target, _settings, _old = profile
    original = source.read_bytes()
    deny_settings_copy(monkeypatch, source, partial)
    requests = []
    monkeypatch.setattr(cfg, "fetch_online_config", lambda url: requests.append(url) or {})
    settings = cfg.load_config()
    assert settings["work_offline"] is True
    assert settings["telemetry_opt_in"] is False
    assert settings["update_check_enabled"] is False
    assert not any(requests)
    assert not target.exists() and not Path(str(target) + ".corrupt").exists()
    assert not list(target.parent.glob("*.tmp"))
    assert source.read_bytes() == original


@pytest.mark.parametrize("partial", [False, True])
def test_failed_profile_copy_retries_without_partial_destination(profile, monkeypatch, partial):
    source, target, settings, _old = profile
    original = source.read_bytes()
    with monkeypatch.context() as failure:
        deny_settings_copy(failure, source, partial)
        cfg.migrate_legacy_app_data()
    assert not target.exists()
    assert source.read_bytes() == original
    # The legacy migration is once per process; model the next launch.
    monkeypatch.setattr(cfg, "_legacy_migration_done", False)
    cfg.migrate_legacy_app_data()
    assert json.loads(target.read_text(encoding="utf-8")) == settings
    assert source.read_bytes() == original


def test_model_hub_reuse_cannot_reopen_privacy_after_failed_transfer(profile, monkeypatch):
    source, target, _settings, old = profile
    (old["cache"] / "models" / "models--synthetic-fixture").mkdir(parents=True)
    deny_settings_copy(monkeypatch, source)
    requests = []
    monkeypatch.setattr(cfg, "fetch_online_config", lambda url: requests.append(url) or {})
    settings = cfg.load_config()
    assert settings["work_offline"] is True and settings["telemetry_opt_in"] is False
    assert not any(requests)
    assert not target.exists(), "automatic hub reuse must not replace unreadable legacy choices"


def test_successful_profile_transfer_still_reuses_old_model_hub(profile):
    source, target, _settings, old = profile
    model_hub = old["cache"] / "models"
    (model_hub / "models--synthetic-fixture").mkdir(parents=True)
    original = source.read_bytes()
    settings = cfg.load_config(fetch_online=False)
    assert settings["work_offline"] is True and settings["telemetry_opt_in"] is False
    assert settings["theme"] == "dark" and settings["hub_folder"] == str(model_hub)
    assert target.is_file() and source.read_bytes() == original


def test_explicit_new_privacy_choice_survives_next_launch(profile, monkeypatch):
    source, target, _settings, _old = profile
    deny_settings_copy(monkeypatch, source)
    settings = cfg.load_config(fetch_online=False)
    assert settings["work_offline"] is True
    settings.update(work_offline=False, telemetry_opt_in=True, update_check_enabled=True)
    cfg.save_config(settings)
    monkeypatch.setattr(cfg, "_legacy_migration_done", False)
    reloaded = cfg.load_config(fetch_online=False)
    assert target.is_file() and source.is_file()
    assert reloaded["work_offline"] is False and reloaded["telemetry_opt_in"] is True
    assert reloaded["update_check_enabled"] is True


def test_failed_profile_sync_retains_privacy_and_original(profile, monkeypatch):
    source, target, _settings, _old = profile
    original = source.read_bytes()

    def deny_sync(*args):
        raise OSError(errno.ENOSPC, "synthetic config sync failure")

    monkeypatch.setattr(cfg.os, "fsync", deny_sync)
    settings = cfg.load_config(fetch_online=False)
    assert settings["work_offline"] is True and settings["telemetry_opt_in"] is False
    assert not target.exists() and source.read_bytes() == original
    assert not list(target.parent.glob("*.tmp"))
