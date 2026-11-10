"""Download bandwidth settings are strict, persisted and frozen per task."""
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from app.domain.tasks import VideoDownloadTask
from app.services.download_service import DownloadService, build_download_command, build_subtitle_command
from core.config import DEFAULT_CONFIG, parse_download_rate_limit, validate_download_rate_limit


@pytest.mark.parametrize("raw, expected", [("", 0), ("  ", 0), ("1", 1), (" 1024 ", 1024)])
def test_parse_rate(raw, expected):
    assert parse_download_rate_limit(raw) == expected


@pytest.mark.parametrize("raw", ["0", "-1", "1.5", "1M", "--exec calc", "1 2", "١", "1e3", "2147483648"])
def test_parse_rejects_invalid_rate(raw):
    with pytest.raises(ValueError):
        parse_download_rate_limit(raw)


@pytest.mark.parametrize("raw", [True, -1, 1.5, "1024", None, 2147483648])
def test_config_rejects_invalid_rate(raw):
    with pytest.raises(ValueError):
        validate_download_rate_limit(raw)


@pytest.mark.parametrize("mode", ["Audio", "Audio and video"])
@pytest.mark.parametrize("rate", [0, 256])
def test_all_commands_capture_rate(mode, rate):
    task = VideoDownloadTask("https://example.com/a", ".", "test", {"mode": mode}, download_rate_limit_kib=rate)
    commands = [build_download_command(task, yt_dlp_path="ytdlp", bin_path=""), build_subtitle_command(task, "en", yt_dlp_path="ytdlp", bin_path="")]
    for cmd in commands:
        if rate:
            index = cmd.index("--limit-rate")
            assert cmd[index + 1] == "262144"
            assert index < cmd.index("--")
        else:
            assert "--limit-rate" not in cmd


@pytest.mark.parametrize("method", ["enqueue_from_form", "enqueue_caption_only_from_form"])
def test_bad_form_rate_changes_nothing(method):
    app = SimpleNamespace(download_rate_limit_var=SimpleNamespace(get=lambda: "1M"), app_config=dict(DEFAULT_CONFIG), download_queue=[])
    before = dict(app.app_config)
    service = DownloadService(app)
    with patch("tkinter.messagebox.showwarning") as warning, patch("app.services.download_service.save_config") as save:
        getattr(service, method)()
    warning.assert_called_once()
    save.assert_not_called()
    assert app.app_config == before
    assert app.download_queue == []

def test_apply_invalid_rate_does_not_save():
    from app.app import App
    app = SimpleNamespace(download_rate_limit_var=SimpleNamespace(get=lambda: "-1"), app_config=dict(DEFAULT_CONFIG))
    with patch("tkinter.messagebox.showwarning") as warning, patch("app.app.save_config") as save:
        App._save_download_rate_limit(app)
    warning.assert_called_once()
    save.assert_not_called()
    assert app.app_config["download_rate_limit_kib"] == 0


def test_apply_rate_persists():
    from app.app import App
    app = SimpleNamespace(download_rate_limit_var=SimpleNamespace(get=lambda: "256"), app_config=dict(DEFAULT_CONFIG), _save_download_prefs=Mock())
    with patch("app.app.save_config") as save:
        App._save_download_rate_limit(app)
    assert app.app_config["download_rate_limit_kib"] == 256
    app._save_download_prefs.assert_called_once()

@pytest.fixture
def isolated_rate_config(tmp_path, monkeypatch):
    from core import config
    for name in ("config", "cache", "log", "data"):
        monkeypatch.setattr(config, "user_" + name + "_dir", lambda n=name: tmp_path / n)
    path = tmp_path / "config" / "config.json"
    path.parent.mkdir()
    monkeypatch.setattr(config, "config_path", lambda: str(path))
    monkeypatch.setattr(config, "_legacy_config_path", lambda: str(tmp_path / "absent.json"))
    return config, path


@pytest.mark.parametrize("value", [True, -1, 2.5, "256", None])
def test_load_invalid_rate_restores_unlimited(isolated_rate_config, value):
    import json
    config, path = isolated_rate_config
    path.write_text(json.dumps({"download_rate_limit_kib": value}), encoding="utf-8")
    assert config.load_config(fetch_online=False)["download_rate_limit_kib"] == 0


def test_rate_survives_save_reload(isolated_rate_config):
    config, path = isolated_rate_config
    cfg = config.load_config(fetch_online=False)
    cfg["download_rate_limit_kib"] = 256
    config.save_config(cfg)
    assert config.load_config(fetch_online=False)["download_rate_limit_kib"] == 256
    before = path.read_bytes()
    cfg["download_rate_limit_kib"] = -1
    with pytest.raises(ValueError):
        config.save_config(cfg)
    assert path.read_bytes() == before

def test_time_range_limit_warns_and_task_keeps_rate(monkeypatch, tmp_path):
    from tests.core.test_fixpack_bl_downloadsvc import _bare_app, _Var
    app, service, captured = _bare_app(monkeypatch, tmp_path, url="https://example.com/video", episode=None)
    app.download_rate_limit_var = _Var("256")
    app.audio_format_var = _Var("Best audio")
    app.audio_format_map = {"Best audio": {"kind": "best_audio"}}
    app.video_format_map = {"SD 396p": {"kind": "format_id", "format_id": "18"}}
    app.download_start_time_var.set("5")
    service.enqueue_from_form()
    task = app.download_queue[0]
    assert "speed limit unavailable" in task.format_label
    assert any("time range" in str(event).lower() and "speed limit" in str(event).lower() for event in captured["events"])
    app.download_rate_limit_var.set("1024")
    app.app_config["download_rate_limit_kib"] = 1024
    assert task.download_rate_limit_kib == 256
