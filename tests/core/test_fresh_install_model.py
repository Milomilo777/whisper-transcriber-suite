"""A new install starts on Large v3 Turbo; an existing config.json keeps its model (core.config)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import config as cfg
from core.model_manager import resolve_model_entry


@pytest.fixture
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point every app folder at tmp_path; returns the config.json path."""
    for kind in ("config", "cache", "log", "data"):
        folder = tmp_path / kind
        folder.mkdir()
        monkeypatch.setattr(cfg, f"user_{kind}_dir", lambda folder=folder: folder)
    path = tmp_path / "config" / "config.json"
    monkeypatch.setattr(cfg, "config_path", lambda: str(path))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json"))
    return path


def _load() -> dict:
    return cfg.load_config(fetch_online=False)


def test_the_fresh_install_entry_is_the_catalog_entry() -> None:
    assert cfg.FRESH_INSTALL_MODEL == resolve_model_entry(cfg.FRESH_INSTALL_MODEL_SLUG)
    assert cfg.FRESH_INSTALL_MODEL_SLUG == "large-v3-turbo"
    # DEFAULT_CONFIG itself is untouched: a saved file without the key still means Large v3.
    assert cfg.DEFAULT_CONFIG["whisper_model"] == "large-v3"
    assert cfg.DEFAULT_CONFIG["model"]["name"] == "faster-whisper-large-v3"


def test_a_new_install_starts_on_turbo_and_saves_it(isolated_config: Path) -> None:
    assert not isolated_config.exists()
    config = _load()
    assert config["whisper_model"] == "large-v3-turbo"
    assert config["model"] == cfg.FRESH_INSTALL_MODEL
    cfg.save_config(config)
    saved = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert saved["whisper_model"] == "large-v3-turbo"
    assert saved["model"]["name"] == "faster-whisper-large-v3-turbo"
    # the second start reads the saved pick the ordinary way
    assert _load()["whisper_model"] == "large-v3-turbo"


def test_an_existing_config_keeps_large_v3(isolated_config: Path) -> None:
    isolated_config.write_text(json.dumps({"whisper_model": "large-v3", "theme": "dark"}), encoding="utf-8")
    config = _load()
    assert config["whisper_model"] == "large-v3"
    assert config["model"]["name"] == "faster-whisper-large-v3"


def test_an_existing_config_without_the_key_still_means_large_v3(isolated_config: Path) -> None:
    """Older versions saved only the keys that differ from the defaults."""
    isolated_config.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    config = _load()
    assert config["whisper_model"] == "large-v3"
    assert config["model"]["name"] == "faster-whisper-large-v3"
    cfg.save_config(config)
    assert "whisper_model" not in json.loads(isolated_config.read_text(encoding="utf-8"))


def test_an_existing_config_with_another_model_keeps_it(isolated_config: Path) -> None:
    isolated_config.write_text(json.dumps({"whisper_model": "small"}), encoding="utf-8")
    assert _load()["whisper_model"] == "small"


def test_an_unreadable_config_counts_as_an_existing_install(isolated_config: Path) -> None:
    Path(str(isolated_config) + ".corrupt").write_text("{nope", encoding="utf-8")
    assert _load()["whisper_model"] == "large-v3"


def test_a_locked_config_is_never_given_the_new_install_model(isolated_config: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    """config.json exists but cannot be read at launch (no last good copy): its model is
    unknown, and a later save of another key must not write Turbo over it."""
    isolated_config.write_text(json.dumps({"whisper_model": "small", "theme": "dark"}),
                               encoding="utf-8")
    real = cfg._read_config_file
    monkeypatch.setattr(cfg, "_read_config_file", lambda path, **kw: ("unreadable", None))
    monkeypatch.setattr(cfg, "_LAST_GOOD", None)
    config = _load()
    monkeypatch.setattr(cfg, "_read_config_file", real)
    assert config["whisper_model"] != cfg.FRESH_INSTALL_MODEL_SLUG
    config["batch_size"] = 12
    cfg.save_config(config)
    disk = json.loads(isolated_config.read_text(encoding="utf-8"))
    assert disk["whisper_model"] == "small" and disk["batch_size"] == 12


def test_a_counter_only_config_is_still_a_new_install(isolated_config: Path) -> None:
    """A headless first run (the server with a cloud engine) writes only its minute counter."""
    isolated_config.write_text(json.dumps({"cloud_stt_minutes_used": 2.0}), encoding="utf-8")
    assert _load()["whisper_model"] == cfg.FRESH_INSTALL_MODEL_SLUG
