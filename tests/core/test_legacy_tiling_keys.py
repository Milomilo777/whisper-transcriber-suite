"""The Video Tiling tab is gone from the GUI; configs written by older versions
still hold its keys. They must load without an error, and the GUI must not
build a tiling tab or keep any tiling handler.
"""
from __future__ import annotations

import inspect
import json
import sys
import types

import pytest

from core import config as cfg


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    config_dir = tmp_path / "config"
    monkeypatch.setattr(cfg, "user_config_dir", lambda: config_dir)
    monkeypatch.setattr(cfg, "user_cache_dir", lambda: tmp_path / "cache")
    monkeypatch.setattr(cfg, "user_log_dir", lambda: tmp_path / "log")
    monkeypatch.setattr(cfg, "user_data_dir", lambda: tmp_path / "data")
    monkeypatch.setattr(cfg, "config_path", lambda: str(config_dir / "config.json"))
    monkeypatch.setattr(
        cfg, "_legacy_config_path", lambda: str(tmp_path / "no_legacy.json")
    )
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.mark.parametrize(
    "tiling_keys",
    [
        {
            "tiling_quality": "720p",
            "tiling_mute": True,
            "tiling_multi_monitor": True,
            "tiling_selected_monitors": [0, 1],
            "tiling_auto_restart": False,
            "tiling_divisions": 5,
        },
        # Junk of the wrong type must not raise either.
        {
            "tiling_quality": None,
            "tiling_mute": "yes",
            "tiling_selected_monitors": "all",
            "tiling_divisions": {"n": 3},
        },
        # A key no version ever defined.
        {"tiling_something_removed_later": [1, 2, 3]},
    ],
)
def test_old_config_with_tiling_keys_loads(isolated_dirs, tiling_keys):
    payload = {"theme": "light", "parallel_workers": 3, **tiling_keys}
    (isolated_dirs / "config.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = cfg.load_config(fetch_online=False)

    # Other settings are untouched by the stale keys.
    assert loaded["theme"] == "light"
    assert loaded["parallel_workers"] == 3


def test_old_tiling_keys_are_dropped_on_the_next_save(isolated_dirs):
    """The tiling engine and its ffplay download links are gone: the next save
    removes their keys from config.json and keeps every other setting."""
    stale = {
        "theme": "light", "parallel_workers": 3,
        "tiling_quality": "720p", "tiling_mute": True, "tiling_multi_monitor": True,
        "tiling_selected_monitors": [0, 1], "tiling_auto_restart": False,
        "tiling_divisions": 5,
        "ffplay_downloads": {"windows": "https://example.com/ffplay.zip"},
    }
    (isolated_dirs / "config.json").write_text(json.dumps(stale), encoding="utf-8")
    cfg.save_config(cfg.load_config(fetch_online=False))
    on_disk = json.loads((isolated_dirs / "config.json").read_text(encoding="utf-8"))
    assert not [k for k in on_disk if k.startswith("tiling_") or k == "ffplay_downloads"]
    assert on_disk["theme"] == "light" and on_disk["parallel_workers"] == 3
    assert "ffplay_downloads" not in cfg.DEFAULT_CONFIG
    assert "ffplay_downloads" not in cfg.ONLINE_ALLOWED_KEYS
    assert not [k for k in cfg.DEFAULT_CONFIG if k.startswith("tiling_")]


@pytest.fixture
def app_mod():
    if "faster_whisper" not in sys.modules:
        fw = types.ModuleType("faster_whisper")
        fw.WhisperModel = object  # type: ignore[attr-defined]
        sys.modules["faster_whisper"] = fw
    import app.app as m
    return m


def test_gui_has_no_tiling_tab_or_handlers(app_mod):
    from app.widgets import tabs

    assert not hasattr(tabs, "build_tiling_tab")
    leftovers = [
        name for name in dir(app_mod.App)
        if "tiling" in name.lower() or "ffplay" in name.lower()
    ]
    assert leftovers == []
    build_tabs_src = inspect.getsource(app_mod.App._build_tabs)
    assert "tiling" not in build_tabs_src.lower()
    assert "Video Tiling" not in build_tabs_src
