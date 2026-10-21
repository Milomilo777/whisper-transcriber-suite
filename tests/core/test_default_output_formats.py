"""Plain text (.txt) is among the default output formats of a new install only.

Users without subtitle tools had no file they could open in a text editor (deep review of
tabs 1-3, 2026-10-21). A config.json from an earlier version keeps the formats it ran with
(srt + json), and a fresh install's choice is written with its first save, so it does not
turn into the old default on the next launch.
"""
from __future__ import annotations

import json

import pytest

from core import config


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "fetch_online_config", lambda url: {})
    monkeypatch.setattr(config.platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path / "data"))
    monkeypatch.setattr(config.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config"))
    yield tmp_path


def _saved(tmp_path) -> dict:
    return json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))


def test_the_shipped_default_has_txt() -> None:
    assert config.DEFAULT_CONFIG["output_formats"] == ["srt", "json", "txt"]


def test_a_new_install_gets_txt_and_keeps_it_after_a_restart(isolated_config) -> None:
    cfg = config.load_config(fetch_online=False)
    assert cfg["output_formats"] == ["srt", "json", "txt"]
    cfg["theme"] = "dark"  # any first save
    config.save_config(cfg)
    assert _saved(isolated_config)["output_formats"] == ["srt", "json", "txt"]
    assert config.load_config(fetch_online=False)["output_formats"] == ["srt", "json", "txt"]


def test_an_earlier_install_keeps_srt_and_json(isolated_config) -> None:
    (isolated_config / "config.json").write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
    cfg = config.load_config(fetch_online=False)
    assert cfg["output_formats"] == ["srt", "json"]
    config.save_config(cfg)
    assert _saved(isolated_config)["output_formats"] == ["srt", "json"]
    assert config.load_config(fetch_online=False)["output_formats"] == ["srt", "json"]


def test_a_users_own_choice_is_untouched(isolated_config) -> None:
    (isolated_config / "config.json").write_text(
        json.dumps({"output_formats": ["vtt"]}), encoding="utf-8")
    assert config.load_config(fetch_online=False)["output_formats"] == ["vtt"]


def test_an_empty_settings_file_counts_as_new_and_stays_so(isolated_config) -> None:
    """An existing but empty config.json (no choice made yet) saves only what changed: the
    formats must be written then too, or the next launch reads it as an earlier install."""
    (isolated_config / "config.json").write_text("{}", encoding="utf-8")
    cfg = config.load_config(fetch_online=False)
    assert cfg["output_formats"] == ["srt", "json", "txt"]
    cfg["theme"] = "dark"
    config.save_config(cfg)
    assert config.load_config(fetch_online=False)["output_formats"] == ["srt", "json", "txt"]
