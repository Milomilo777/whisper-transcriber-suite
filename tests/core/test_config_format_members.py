"""Malformed format entries must not block recovery through Advanced settings."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import config


@pytest.mark.parametrize("invalid", [{}, ["json"], None, True, 1])
def test_loaded_formats_keep_valid_choices_and_reject_nested_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, invalid: object,
) -> None:
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path))
    path = Path(config.config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    original = json.dumps({"output_formats": ["vtt", invalid], "theme": "dark"})
    path.write_text(original, encoding="utf-8")
    loaded = config.load_config(fetch_online=False)
    assert loaded["output_formats"] == ["vtt"]
    assert loaded["theme"] == "dark"
    # Advanced settings builds a set from the loaded formats.
    assert set(loaded["output_formats"]) == {"vtt"}
    assert path.read_text(encoding="utf-8") == original


def test_entirely_malformed_formats_use_independent_default_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path))
    path = Path(config.config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"output_formats": [{}]}', encoding="utf-8")
    loaded = config.load_config(fetch_online=False)
    assert loaded["output_formats"] == config.DEFAULT_CONFIG["output_formats"]
    assert loaded["output_formats"] is not config.DEFAULT_CONFIG["output_formats"]


@pytest.mark.parametrize("formats", [[], ["future_format", "vtt", "txt"]])
def test_valid_format_strings_keep_order_and_empty_choice(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, formats: list[str],
) -> None:
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path))
    path = Path(config.config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"output_formats": formats}), encoding="utf-8")
    assert config.load_config(fetch_online=False)["output_formats"] == formats


def test_normal_save_persists_format_repair_and_preserves_other_choices(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WTS_PROFILE_DIR", str(tmp_path))
    path = Path(config.config_path())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"output_formats": ["vtt", {}], "theme": "dark",
                                "telemetry_opt_in": False}), encoding="utf-8")
    loaded = config.load_config(fetch_online=False)
    config.save_config(loaded)
    reloaded = config.load_config(fetch_online=False)
    assert reloaded["output_formats"] == ["vtt"]
    assert reloaded["theme"] == "dark"
    assert reloaded["telemetry_opt_in"] is False
    assert json.loads(path.read_text(encoding="utf-8"))["output_formats"] == ["vtt"]
