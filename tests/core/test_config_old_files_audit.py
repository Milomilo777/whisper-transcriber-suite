"""Config files saved by older releases, and damaged ones, still load."""
import json
from pathlib import Path

import pytest

from core import config

FIXTURES = Path(__file__).parent / "fixtures" / "old_configs"

@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_path", lambda: str(tmp_path / "config.json"))
    monkeypatch.setattr(config, "fetch_online_config", lambda url: {})
    # Mock legacy paths so it doesn't try to actually migrate things from user dirs
    monkeypatch.setattr(config.platformdirs, "user_data_dir", lambda *a, **k: str(tmp_path / "data"))
    monkeypatch.setattr(config.platformdirs, "user_config_dir", lambda *a, **k: str(tmp_path / "config"))
    yield tmp_path

def test_load_old_files(isolated_config):
    # Test all old versions load properly without raising and preserve standard options
    for v in ["v1.5.0", "v1.8.0", "v1.9.3", "v2.0.0"]:
        with open(FIXTURES / f"{v}.json", encoding="utf-8") as f:
            data = json.load(f)

        # Customize some things to check they're preserved
        data["theme"] = "dark"
        data["model"]["name"] = "faster-whisper-medium"
        data["transcribe_language"] = "French"
        data["output_formats"] = ["txt", "vtt"]

        with open(isolated_config / "config.json", "w") as f:
            json.dump(data, f)

        cfg = config.load_config(fetch_online=False)

        assert cfg["theme"] == "dark"
        assert cfg["model"]["name"] == "faster-whisper-medium"
        assert cfg["transcribe_language"] == "French"
        assert "vtt" in cfg["output_formats"]

def test_load_damaged_files(isolated_config, caplog):
    # Empty file
    (isolated_config / "config.json").write_text("")
    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "light" # default
    assert "not a valid JSON object" in caplog.text or "not a JSON object" in caplog.text or "cannot be read" in caplog.text

    caplog.clear()

    # Truncated JSON
    (isolated_config / "config.json").write_text('{"theme": "dark", "model": ')
    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "light"
    assert "not a valid JSON object" in caplog.text or "corrupt" in caplog.text or "Could not read" in caplog.text

    caplog.clear()

    # BOM / CRLF
    (isolated_config / "config.json").write_bytes(b'\xef\xbb\xbf{\r\n  "theme": "dark"\r\n}')
    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"

    caplog.clear()

    # Wrong type
    (isolated_config / "config.json").write_text('{"theme": "dark", "parallel_workers": "four"}')
    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"
    # Should fall back to default
    assert cfg["parallel_workers"] == 2

    caplog.clear()

    # Unknown key (these are deliberately preserved across loads so a newer version's key is not deleted by an older version)
    (isolated_config / "config.json").write_text('{"theme": "dark", "unknown_future_key": 42}')
    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"
    assert "unknown_future_key" in cfg
    assert cfg["unknown_future_key"] == 42

    caplog.clear()

def test_save_atomic_unknown_keys(isolated_config):
    (isolated_config / "config.json").write_text('{"theme": "dark", "unknown_future_key": 42}')
    cfg = config.load_config(fetch_online=False)

    # Save a known key
    cfg["theme"] = "light"
    config.save_config(cfg)

    # Reload and ensure the unknown key is still there
    new_data = json.loads((isolated_config / "config.json").read_text())
    assert new_data["theme"] == "light"
    assert "unknown_future_key" in new_data
    assert new_data["unknown_future_key"] == 42

def test_load_damaged_file_backs_up(isolated_config):
    # Write corrupt json
    (isolated_config / "config.json").write_text('{"theme": "dark", ')

    cfg = config.load_config(fetch_online=False)

    assert cfg["theme"] == "light" # defaulted

    # Check that backup exists
    assert (isolated_config / "config.json.corrupt").exists()
    assert (isolated_config / "config.json.corrupt").read_text() == '{"theme": "dark", '

def test_readonly_file(isolated_config, monkeypatch, caplog):
    # Setup config
    config_file = isolated_config / "config.json"
    config_file.write_text('{"theme": "dark"}')

    # Note: On many environments, root/docker run doesn't enforce standard permissions,
    # but saving safely on a permission error usually backs out silently returning False,
    # or raises ConfigSaveError. Since save_config returns a bool for success:
    config_file.chmod(0o444) # Read only

    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"

    cfg["theme"] = "light"

    # Save failure when file is read-only will just warn and return False instead of raising
    # On linux root, the chmod might not do anything, so we'll mock the replace instead
    import os
    orig_replace = os.replace
    def mocked_replace(*args, **kwargs):
        raise PermissionError("Mocked permission error")
    monkeypatch.setattr(os, "replace", mocked_replace)

    with pytest.raises(config.ConfigSaveError) as exc:
        config.save_config(cfg)

    assert "Mocked permission error" in str(exc.value)

    config_file.chmod(0o666) # Cleanup
    caplog.clear()

def test_non_ascii_path(tmp_path, monkeypatch):
    non_ascii_path = tmp_path / "測試"
    non_ascii_path.mkdir()

    config_file = non_ascii_path / "config.json"
    monkeypatch.setattr(config, "config_path", lambda: str(config_file))
    monkeypatch.setattr(config, "fetch_online_config", lambda url: {})

    config_file.write_text('{"theme": "dark"}')

    cfg = config.load_config(fetch_online=False)
    assert cfg["theme"] == "dark"


def test_load_damaged_files_drops_wrong_type(isolated_config, caplog):
    # Verify exact log messages that keys with wrong type/unrecognized are dropped with notice
    (isolated_config / "config.json").write_text('{"theme": "dark", "parallel_workers": "four"}')
    cfg = config.load_config(fetch_online=False)

    assert cfg["parallel_workers"] == 2
    assert "has wrong type" in caplog.text
    assert "parallel_workers" in caplog.text

def test_dropped_keys_log(isolated_config, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        (isolated_config / "config.json").write_text('{"theme": "dark", "auto_update_yt_dlp": true}')
        cfg = config.load_config(fetch_online=False)

    assert cfg["yt_dlp_update_mode"] == "auto"
    assert "migrated auto_update_yt_dlp to yt_dlp_update_mode; dropping old key" in caplog.text
    assert "auto_update_yt_dlp" not in cfg
