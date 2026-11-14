"""Legacy settings survive interrupted publication without reopening privacy switches."""
import errno
import json
from pathlib import Path

import pytest

from core import config as cfg
from core import offline


@pytest.fixture
def migration(tmp_path, monkeypatch):
    folder = tmp_path / "new-config"
    folder.mkdir()
    target = folder / "config.json"
    source = tmp_path / "legacy-config.json"
    data = {"theme": "dark", "work_offline": True,
            "telemetry_opt_in": False, "update_check_enabled": False}
    source.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(cfg, "user_config_dir", lambda: folder)
    for name in ("user_cache_dir", "user_data_dir", "user_log_dir"):
        monkeypatch.setattr(cfg, name, lambda name=name: tmp_path / name)
    monkeypatch.setattr(cfg, "config_path", lambda: str(target))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(source))
    monkeypatch.setattr(cfg, "_legacy_app_dirs", lambda: None)
    monkeypatch.setattr(cfg, "_profile_root", lambda: None)
    monkeypatch.setattr(cfg, "_ONLINE_MEMO", {})
    monkeypatch.setattr(offline, "_override", None)
    monkeypatch.setattr(offline, "_cache_key", None)
    monkeypatch.setattr(offline, "_last_saved", False)
    cfg._forget_last_good()
    yield source, target, data
    cfg._forget_last_good()


def interrupted_copy(monkeypatch, source, partial):
    copy = cfg.shutil.copy2

    def fail(src, destination, *args, **kwargs):
        if Path(src) == source:
            if partial:
                Path(destination).write_bytes(b'{"theme":')
            raise OSError(errno.ENOSPC, "synthetic migration copy failure")
        return copy(src, destination, *args, **kwargs)

    monkeypatch.setattr(cfg.shutil, "copy2", fail)


@pytest.mark.parametrize("partial", [False, True])
def test_failed_migration_leaves_no_final_fragment_and_retries(migration, monkeypatch, partial):
    source, target, data = migration
    original = source.read_bytes()
    with monkeypatch.context() as failure:
        interrupted_copy(failure, source, partial)
        assert cfg.migrate_config_location() == str(target)
    assert source.read_bytes() == original and not target.exists()
    assert not list(target.parent.glob("*.tmp"))
    assert cfg.migrate_config_location() == str(target)
    assert json.loads(target.read_text(encoding="utf-8")) == data
    assert Path(str(source) + ".migrated.bak").read_bytes() == original


@pytest.mark.parametrize("partial", [False, True])
def test_failed_migration_keeps_network_privacy_closed(migration, monkeypatch, partial):
    source, target, _data = migration
    original = source.read_bytes()
    interrupted_copy(monkeypatch, source, partial)
    requests = []
    monkeypatch.setattr(cfg, "fetch_online_config", lambda url: requests.append(url) or {})
    settings = cfg.load_config()
    assert settings["work_offline"] is True
    assert settings["telemetry_opt_in"] is False
    assert settings["update_check_enabled"] is False
    assert not any(requests)
    switches = cfg.read_local_config_for_switches()
    assert switches is not None and switches["work_offline"] is True
    assert switches["telemetry_opt_in"] is False
    assert source.read_bytes() == original


def test_fresh_install_without_legacy_keeps_default_policy(migration, monkeypatch):
    source, target, _data = migration
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(source.with_name("absent.json")))
    settings = cfg.load_config(fetch_online=False)
    for key in ("work_offline", "telemetry_opt_in", "update_check_enabled"):
        assert settings[key] == cfg.DEFAULT_CONFIG[key]
    assert not target.exists()


def test_existing_current_settings_are_not_replaced_by_legacy(migration):
    source, target, _data = migration
    original = source.read_bytes()
    current = {"theme": "light", "work_offline": False, "telemetry_opt_in": True}
    target.write_text(json.dumps(current), encoding="utf-8")
    settings = cfg.load_config(fetch_online=False)
    assert settings["theme"] == "light" and settings["work_offline"] is False
    assert settings["telemetry_opt_in"] is True
    assert json.loads(target.read_text(encoding="utf-8")) == current
    assert Path(str(source) + ".migrated.bak").read_bytes() == original


def test_legacy_byte_encoding_is_preserved_during_copy(migration):
    source, target, _data = migration
    original = b'{"theme":"dark","custom_label":"caf\xe9"}'
    source.write_bytes(original)
    assert cfg.migrate_config_location() == str(target)
    assert target.read_bytes() == original
    assert Path(str(source) + ".migrated.bak").read_bytes() == original


def test_unrelated_save_after_failed_migration_does_not_reopen_network(migration, monkeypatch):
    source, target, _data = migration
    interrupted_copy(monkeypatch, source, False)
    settings = cfg.load_config(fetch_online=False)
    assert settings["work_offline"] is True and settings["telemetry_opt_in"] is False
    settings["log_level"] = "DEBUG"
    cfg.save_config(settings)
    reloaded = cfg.load_config(fetch_online=False)
    assert reloaded["work_offline"] is True and reloaded["telemetry_opt_in"] is False
    assert cfg.read_local_config_for_switches()["work_offline"] is True


def test_explicit_privacy_choice_can_be_saved_after_failed_migration(migration, monkeypatch):
    source, _target, _data = migration
    interrupted_copy(monkeypatch, source, False)
    settings = cfg.load_config(fetch_online=False)
    settings.update(work_offline=False, telemetry_opt_in=True, update_check_enabled=True)
    cfg.save_config(settings)
    reloaded = cfg.load_config(fetch_online=False)
    assert reloaded["work_offline"] is False
    assert reloaded["telemetry_opt_in"] is True
    assert reloaded["update_check_enabled"] is True


def test_partial_update_cannot_replace_failed_legacy_settings(migration, monkeypatch):
    source, target, _data = migration
    interrupted_copy(monkeypatch, source, False)
    settings = cfg.load_config(fetch_online=False)
    assert settings["work_offline"] is True
    with pytest.raises(cfg.ConfigSaveError, match="legacy"):
        cfg.update_config(lambda data: data.__setitem__("hub_folder", "synthetic-hub"))
    assert not target.exists()
    assert cfg.load_config(fetch_online=False)["telemetry_opt_in"] is False


def test_explicit_profile_does_not_inherit_legacy_failure_policy(migration, monkeypatch, tmp_path):
    source, target, _data = migration
    monkeypatch.setattr(cfg, "_profile_root", lambda: tmp_path / "isolated-profile")
    settings = cfg.load_config(fetch_online=False)
    for key in ("work_offline", "telemetry_opt_in", "update_check_enabled"):
        assert settings[key] == cfg.DEFAULT_CONFIG[key]
    assert source.is_file() and not target.exists()


@pytest.mark.parametrize("operation", ["fsync", "publish"])
def test_failure_after_copy_keeps_original_and_retries(migration, monkeypatch, operation):
    source, target, _data = migration
    original = source.read_bytes()

    def fail(*args, **kwargs):
        raise cfg.ConfigSaveError("synthetic publication failure")

    with monkeypatch.context() as failure:
        if operation == "fsync":
            failure.setattr(cfg.os, "fsync", fail)
        else:
            # Migration publishes without replacing a competing settings save.
            failure.setattr(cfg.os, "rename" if cfg.sys.platform == "win32" else "link", fail)
        assert cfg.migrate_config_location() == str(target)
    assert source.read_bytes() == original and not target.exists()
    assert not list(target.parent.glob("*.tmp"))
    cfg.migrate_config_location()
    assert target.read_bytes() == original


def test_read_only_staged_copy_is_removed_on_publication_failure(migration, monkeypatch):
    source, target, _data = migration
    source.chmod(0o400)

    def fail(*args):
        raise cfg.ConfigSaveError("synthetic publication failure")

    try:
        with monkeypatch.context() as failure:
            failure.setattr(cfg.os, "rename" if cfg.sys.platform == "win32" else "link", fail)
            cfg.migrate_config_location()
        assert source.is_file() and not target.exists()
        assert not list(target.parent.glob("*.tmp"))
    finally:
        source.chmod(0o600)
