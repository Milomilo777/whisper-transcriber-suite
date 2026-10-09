"""How ``core.config`` treats odd-but-parseable values and files.

Covers the type coercions of ``load_project_overrides`` (an int for a bool
key, a float for an int key and the reverse, a wrong container type), the
non-finite float and empty-file cases of ``load_config``, and a non-ASCII
folder name that must pass through unchanged. Hermetic: every directory is
redirected under ``tmp_path``.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import config
from core.config import PROJECT_FILE_NAME, load_project_overrides


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(config, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(config, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(config, "user_log_dir", lambda: tmp_path / "log")
    monkeypatch.setattr(config, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(config, "config_path", lambda: str(config_dir / "config.json"))
    monkeypatch.setattr(
        config, "_legacy_config_path", lambda: str(config_dir / "no_legacy.json")
    )
    return tmp_path


def _project(tmp_path: Path, payload: str) -> Path:
    media = tmp_path / "talk.mp4"
    (tmp_path / PROJECT_FILE_NAME).write_text(payload, encoding="utf-8")
    return media


# --- project overrides: coercion of numbers and booleans -------------------


def test_int_for_a_bool_key_becomes_a_bool(tmp_path):
    media = _project(tmp_path, '{"vad_enabled": 1, "demucs_enabled": 0}')
    overrides = load_project_overrides(str(media))
    assert overrides["vad_enabled"] is True
    assert overrides["demucs_enabled"] is False


def test_float_for_an_int_key_is_truncated_to_an_int(tmp_path):
    media = _project(tmp_path, '{"batch_size": 2.5}')
    overrides = load_project_overrides(str(media))
    assert overrides["batch_size"] == 2
    assert isinstance(overrides["batch_size"], int)


def test_int_for_a_float_key_becomes_a_float(tmp_path):
    media = _project(tmp_path, '{"vad_threshold": 1}')
    overrides = load_project_overrides(str(media))
    assert overrides["vad_threshold"] == 1.0
    assert isinstance(overrides["vad_threshold"], float)


def test_a_float_that_truncates_below_the_range_is_dropped(tmp_path):
    media = _project(tmp_path, '{"batch_size": 0.9}')
    assert load_project_overrides(str(media)) == {}


@pytest.mark.parametrize(
    "payload",
    [
        '{"output_formats": "srt"}',  # a string where a list belongs
        '{"hotwords": ["a", "b"]}',  # a list where a string belongs
        '{"batch_size": "4"}',  # a numeric string is not a number
        '{"vad_enabled": "yes"}',  # a string is not a bool
    ],
)
def test_a_value_of_the_wrong_type_is_dropped(tmp_path, payload):
    assert load_project_overrides(str(_project(tmp_path, payload))) == {}


def test_a_bad_value_does_not_drop_its_valid_neighbours(tmp_path):
    media = _project(tmp_path, '{"batch_size": "4", "vad_threshold": 0.25}')
    assert load_project_overrides(str(media)) == {"vad_threshold": 0.25}


# --- load_config: odd files and values -------------------------------------


def test_float_that_overflows_to_infinity_reverts_to_the_default(isolated_dirs):
    Path(config.config_path()).write_text('{"vad_threshold": 1e400}', encoding="utf-8")
    loaded = config.load_config(fetch_online=False)
    assert loaded["vad_threshold"] == config.DEFAULT_CONFIG["vad_threshold"]


@pytest.mark.parametrize("text", ["", "   \n\t  \n"])
def test_empty_or_blank_config_file_gives_the_defaults(isolated_dirs, text):
    Path(config.config_path()).write_text(text, encoding="utf-8")
    loaded = config.load_config(fetch_online=False)
    assert loaded["model"]["name"] == config.DEFAULT_CONFIG["model"]["name"]
    assert loaded["vad_threshold"] == config.DEFAULT_CONFIG["vad_threshold"]


def test_a_string_for_the_model_dict_keeps_the_default_model(isolated_dirs):
    Path(config.config_path()).write_text('{"model": "string"}', encoding="utf-8")
    loaded = config.load_config(fetch_online=False)
    assert isinstance(loaded["model"], dict)
    assert loaded["model"]["name"] == config.DEFAULT_CONFIG["model"]["name"]


def test_a_persian_download_folder_survives_a_load(isolated_dirs):
    folder = isolated_dirs / "پوشه-دانلود"
    folder.mkdir()
    Path(config.config_path()).write_text(
        json.dumps({"download_folder": str(folder)}), encoding="utf-8"
    )
    loaded = config.load_config(fetch_online=False)
    assert loaded["download_folder"] == str(folder)
