"""Legacy hardware settings must migrate completely and retry after I/O failure."""
import errno
from pathlib import Path

import pytest

from core import config as cfg
from tests.core.test_legacy_app_migration import dirs


@pytest.fixture
def hardware_profile(dirs):
    new, old = dirs
    (old["config"] / "config.json").write_text('{"theme": "dark"}', encoding="utf-8")
    source = old["data"] / "hardware.json"
    original = b'{"version": 1, "device": "cpu", "compute_type": "int8"}'
    source.write_bytes(original)
    return new, old, source, original


def test_partial_copy_never_becomes_current_hardware(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    destination = new["data"] / "hardware.json"
    copy = cfg.shutil.copy2

    def fail_mid_copy(src, dst, *args, **kwargs):
        if Path(src) == source:
            Path(dst).write_bytes(original[:11])
            raise OSError(errno.ENOSPC, "synthetic partial hardware copy")
        return copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(cfg.shutil, "copy2", fail_mid_copy)
    cfg.migrate_legacy_app_data()
    assert not destination.exists(), "failed legacy copy exposed incomplete hardware settings"
    assert source.read_bytes() == original
    assert not list(new["data"].glob(".migration-*"))


def test_failed_copy_retries_after_settings_were_created(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    copy = cfg.shutil.copy2

    def fail_hardware(src, dst, *args, **kwargs):
        if Path(src) == source:
            raise OSError(errno.EACCES, "synthetic transient hardware refusal")
        return copy(src, dst, *args, **kwargs)

    with monkeypatch.context() as fault:
        fault.setattr(cfg.shutil, "copy2", fail_hardware)
        cfg.migrate_legacy_app_data()
    assert (new["config"] / "config.json").is_file()
    assert not (new["data"] / "hardware.json").exists()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert (new["data"] / "hardware.json").read_bytes() == original
    assert source.read_bytes() == original


def test_racing_current_hardware_choice_wins(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    destination = new["data"] / "hardware.json"
    choice = b'{"device": "cuda", "compute_type": "float16"}'
    copy = cfg.shutil.copy2

    def create_current_during_copy(src, dst, *args, **kwargs):
        if Path(src) == source:
            destination.write_bytes(choice)
        return copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(cfg.shutil, "copy2", create_current_during_copy)
    cfg.migrate_legacy_app_data()
    assert destination.read_bytes() == choice
    assert source.read_bytes() == original


def test_hardware_intent_failure_does_not_hide_retry_after_explicit_save(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    write = cfg._write_disk_dict

    def refuse_intent(path, value):
        if Path(path).name == "legacy-hardware-migration.json":
            raise OSError(errno.ENOSPC, "synthetic hardware intent failure")
        return write(path, value)

    with monkeypatch.context() as fault:
        fault.setattr(cfg, "_write_disk_dict", refuse_intent)
        cfg.migrate_legacy_app_data()
        with pytest.raises(cfg.ConfigSaveError):
            cfg.save_config({"theme": "light"})
    assert not (new["config"] / "config.json").exists()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert (new["data"] / "hardware.json").read_bytes() == original


def test_existing_current_profile_does_not_import_old_hardware(hardware_profile):
    new, old, source, original = hardware_profile
    (new["config"] / "config.json").write_text('{"theme": "light"}', encoding="utf-8")
    cfg.migrate_legacy_app_data()
    assert not (new["data"] / "hardware.json").exists()


def test_completed_hardware_transfer_does_not_resurrect_removed_choice(hardware_profile):
    new, old, source, original = hardware_profile
    cfg.migrate_legacy_app_data()
    destination = new["data"] / "hardware.json"
    assert destination.read_bytes() == original
    destination.unlink()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert not destination.exists()
    assert source.read_bytes() == original


def test_sync_failure_keeps_target_missing_and_retryable(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    destination = new["data"] / "hardware.json"
    copy, sync = cfg.shutil.copy2, cfg.os.fsync
    copied_hardware = False

    def copy_hardware(src, dst, *args, **kwargs):
        nonlocal copied_hardware
        value = copy(src, dst, *args, **kwargs)
        if Path(src) == source:
            copied_hardware = True
        return value

    def refuse_hardware_sync(fd):
        if copied_hardware:
            raise OSError(errno.EIO, "synthetic hardware sync failure")
        return sync(fd)

    with monkeypatch.context() as fault:
        fault.setattr(cfg.shutil, "copy2", copy_hardware)
        fault.setattr(cfg.os, "fsync", refuse_hardware_sync)
        cfg.migrate_legacy_app_data()
    assert not destination.exists()
    assert not list(new["data"].glob(".migration-*"))
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert destination.read_bytes() == original
    assert source.read_bytes() == original


def test_hardware_receipt_retry_preserves_newer_choice(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    destination = new["data"] / "hardware.json"
    write = cfg._write_disk_dict

    def refuse_completion(path, value):
        if Path(path).name == "legacy-hardware-migration.json" and value["complete"]:
            raise OSError(errno.ENOSPC, "synthetic completion receipt failure")
        return write(path, value)

    with monkeypatch.context() as fault:
        fault.setattr(cfg, "_write_disk_dict", refuse_completion)
        cfg.migrate_legacy_app_data()
    assert destination.read_bytes() == original
    choice = b'{"device":"cuda","compute_type":"float16"}'
    destination.write_bytes(choice)
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert destination.read_bytes() == choice
    assert source.read_bytes() == original


def test_no_hard_link_support_does_not_publish_partial_hardware(hardware_profile, monkeypatch):
    new, old, source, original = hardware_profile
    destination = new["data"] / "hardware.json"

    def unsupported(*args, **kwargs):
        raise OSError(errno.ENOTSUP, "synthetic unavailable hard link")

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Exercise just publication: platform-wide migration uses Windows file locks.
    with monkeypatch.context() as fault:
        fault.setattr(cfg.sys, "platform", "linux")
        fault.setattr(cfg.os, "link", unsupported)
        with pytest.raises(OSError, match="unavailable hard link"):
            cfg._copy_legacy_settings(source, destination, replace=False)
    assert not destination.exists()
    assert not list(new["data"].glob(".migration-*"))
    cfg._copy_legacy_settings(source, destination, replace=False)
    assert destination.read_bytes() == original
    assert source.read_bytes() == original
