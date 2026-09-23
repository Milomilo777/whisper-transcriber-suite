"""Pre-rebrand (WhisperProject) profile migration for non-installer runs."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import core.config as cfg


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    new = {k: tmp_path / "new" / k for k in ("config", "data", "cache")}
    old = {k: tmp_path / "old" / k for k in ("config", "data", "cache")}
    for p in old.values():
        p.mkdir(parents=True)
    new["config"].mkdir(parents=True)
    monkeypatch.setattr(cfg, "user_config_dir", lambda: new["config"])
    monkeypatch.setattr(cfg, "user_data_dir", lambda: new["data"])
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: new["cache"])
    monkeypatch.setattr(cfg, "config_path", lambda: str(new["config"] / "config.json"))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "none.json"))
    monkeypatch.setattr(cfg, "_legacy_app_dirs", lambda: old)
    monkeypatch.setattr(cfg, "_legacy_migration_done", False)
    return new, old


def _model(hub: Path, name: str = "models--Systran--faster-whisper-large-v3") -> None:
    (hub / name).mkdir(parents=True)
    (hub / name / "model.bin").write_bytes(b"x")


def test_fresh_profile_copies_settings_and_reuses_old_hub(dirs):
    new, old = dirs
    (old["config"] / "config.json").write_text(json.dumps({"theme": "dark"}), "utf-8")
    (old["data"] / "history.db").write_bytes(b"db")
    (old["data"] / "history.db-wal").write_bytes(b"wal")
    _model(old["cache"] / "models")
    (old["cache"] / "llm").mkdir()
    (old["cache"] / "llm" / "m.gguf").write_bytes(b"g")

    config = cfg.load_config(fetch_online=False)

    assert config["theme"] == "dark"
    assert (new["data"] / "history.db").read_bytes() == b"db"
    assert (new["data"] / "history.db-wal").read_bytes() == b"wal"
    assert config["hub_folder"] == str(old["cache"] / "models")
    assert (new["cache"] / "llm" / "m.gguf").is_file()
    assert not (old["cache"] / "llm").exists()
    # Copies, never deletes, the old settings.
    assert (old["config"] / "config.json").is_file()
    assert (old["data"] / "history.db").is_file()


def test_existing_empty_profile_is_rescued_without_overwriting(dirs):
    new, old = dirs
    new_hub = new["cache"] / "models"
    (new["config"] / "config.json").write_text(
        json.dumps({"theme": "light", "hub_folder": str(new_hub)}), "utf-8"
    )
    (old["config"] / "config.json").write_text(json.dumps({"theme": "dark"}), "utf-8")
    _model(old["cache"] / "models")

    config = cfg.load_config(fetch_online=False)

    assert config["theme"] == "light"
    assert config["hub_folder"] == str(old["cache"] / "models")


def test_new_hub_with_models_or_custom_hub_is_left_alone(dirs, tmp_path):
    new, old = dirs
    _model(old["cache"] / "models")
    _model(new["cache"] / "models")
    config = cfg.load_config(fetch_online=False)
    assert str(config.get("hub_folder") or "") in ("", str(new["cache"] / "models"))

    cfg._legacy_migration_done = False
    custom = tmp_path / "custom_hub"
    (new["config"] / "config.json").write_text(
        json.dumps({"hub_folder": str(custom)}), "utf-8"
    )
    assert cfg.load_config(fetch_online=False)["hub_folder"] == str(custom)


def test_existing_new_cache_folder_is_not_replaced(dirs):
    new, old = dirs
    (old["config"] / "config.json").write_text("{}", "utf-8")
    (old["cache"] / "whisper_cpp").mkdir()
    (new["cache"] / "whisper_cpp").mkdir(parents=True)
    cfg.load_config(fetch_online=False)
    assert (old["cache"] / "whisper_cpp").is_dir()


def test_no_legacy_profile_is_a_noop(dirs, monkeypatch):
    new, _old = dirs
    monkeypatch.setattr(cfg, "_legacy_app_dirs", lambda: None)
    cfg.load_config(fetch_online=False)
    assert not (new["config"] / "config.json").exists()
