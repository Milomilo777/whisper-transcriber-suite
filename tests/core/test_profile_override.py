"""WTS_PROFILE_DIR puts every per-user folder under one root (GUI test runs).

Without it a click-through test on a test machine used that machine's real profile:
config.json and history.db changed, and the state before the test was lost
(2026-10-21; LOCALAPPDATA does not redirect platformdirs). With the variable set, the
pre-rebrand profile and a next-to-source config.json are never migrated in, so the real
profile is not touched either.
"""
from __future__ import annotations

from pathlib import Path

import platformdirs

from core import config

# The real function: the suite's conftest patches it to None for every test.
_REAL_LEGACY_APP_DIRS = config._legacy_app_dirs


def test_unset_keeps_platformdirs(monkeypatch):
    monkeypatch.delenv(config.PROFILE_ENV, raising=False)
    assert config.user_config_dir() == Path(platformdirs.user_config_dir(config.APP_NAME, config.APP_AUTHOR))


def test_every_folder_moves_under_the_root(monkeypatch, tmp_path):
    monkeypatch.setenv(config.PROFILE_ENV, str(tmp_path))
    assert config.user_config_dir() == tmp_path / "config"
    assert config.user_cache_dir() == tmp_path / "cache"
    assert config.user_log_dir() == tmp_path / "logs"
    assert config.user_data_dir() == tmp_path / "data"
    assert Path(config.config_path()) == tmp_path / "config" / "config.json"


def test_a_blank_value_is_ignored(monkeypatch):
    monkeypatch.setenv(config.PROFILE_ENV, "   ")
    assert config.user_config_dir() != Path("config")


def test_no_legacy_profile_is_migrated_in(monkeypatch, tmp_path):
    monkeypatch.delenv(config.PROFILE_ENV, raising=False)
    assert _REAL_LEGACY_APP_DIRS() is not None, "control: without the variable it is found"
    monkeypatch.setenv(config.PROFILE_ENV, str(tmp_path / "profile"))
    assert _REAL_LEGACY_APP_DIRS() is None


def test_a_next_to_source_config_is_left_alone(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy" / "config.json"
    legacy.parent.mkdir()
    legacy.write_text('{"ui_language": "fa"}', encoding="utf-8")
    monkeypatch.setattr(config, "_legacy_config_path", lambda: str(legacy))
    monkeypatch.setenv(config.PROFILE_ENV, str(tmp_path / "profile"))

    new_path = config.migrate_config_location()

    assert legacy.exists(), "the real file must not be renamed away"
    assert not Path(new_path).exists()
