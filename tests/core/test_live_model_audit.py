from __future__ import annotations

from unittest.mock import patch


from core import live_model as lm


def test_recommended_cpu_slug_with_default_cpu_count():
    # Characterization test for pure logic.
    with patch("os.cpu_count", return_value=4):
        assert lm.recommended_cpu_slug(None) == "small"
        assert lm.recommended_cpu_slug("en") == "base.en"

    with patch("os.cpu_count", return_value=8):
        assert lm.recommended_cpu_slug(None) == "small"
        assert lm.recommended_cpu_slug("en") == "small.en"

    with patch("os.cpu_count", return_value=None):
        assert lm.recommended_cpu_slug(None) == "small"


def test_resolve_live_slug():
    config = {"live_model": "tiny"}
    assert lm.resolve_live_slug(config, "en", "cpu") == "tiny"

    # MAIN means None
    config["live_model"] = lm.LIVE_MAIN
    assert lm.resolve_live_slug(config, "en", "cpu") is None

    # AUTO resolves based on device
    config["live_model"] = lm.LIVE_AUTO
    # gpu device returns None
    assert lm.resolve_live_slug(config, "en", "cuda") is None
    # cpu device recommends
    assert lm.resolve_live_slug(config, "en", "cpu") == lm.recommended_cpu_slug("en")


def test_effective_live_slug():
    # If resolve is None, it uses the config's whisper_model
    config = {"live_model": lm.LIVE_MAIN, "whisper_model": "large-v3"}
    assert lm.effective_live_slug(config, "en", "cuda") == "large-v3"
    
    # If resolve returns a slug, use it
    config["live_model"] = "tiny"
    assert lm.effective_live_slug(config, "en", "cpu") == "tiny"


def test_live_alternative():
    # If device is cpu, it's the recommended slug.
    config = {"whisper_model": "medium"}
    assert lm.live_alternative(config, "fr", "cpu", "medium.en") == ("small", "small")

    # If gpu and main is multilingual, use main
    config = {"whisper_model": "medium"}
    assert lm.live_alternative(config, "fr", "cuda", "medium.en") == (lm.LIVE_MAIN, "medium")


def test_live_model_config_invalid_slug():
    config = {"hub_folder": "/tmp", "whisper_model": "large"}
    assert lm.live_model_config(config, "nonexistent-slug") is None


def test_apply_env_override(monkeypatch):
    config = {"hub_folder": "/tmp", "model": {}, "whisper_model": "base"}
    
    # Missing env var
    monkeypatch.delenv(lm.LIVE_MODEL_ENV, raising=False)
    assert lm.apply_env_override(config) is None
    
    # Invalid slug in env var
    monkeypatch.setenv(lm.LIVE_MODEL_ENV, "nonexistent")
    assert lm.apply_env_override(config) is None
    
    # Valid slug but weights not present
    monkeypatch.setenv(lm.LIVE_MODEL_ENV, "tiny")
    with patch("core.model_manager.catalog_resolve_entry", return_value={"name": "tiny.bin"}), \
         patch("core.hub.model_weights_present", return_value=False):
        assert lm.apply_env_override(config) is None
        
    # Valid slug and weights present
    monkeypatch.setenv(lm.LIVE_MODEL_ENV, "tiny")
    with patch("core.model_manager.catalog_resolve_entry", return_value={"name": "tiny.bin"}), \
         patch("core.hub.model_weights_present", return_value=True):
        slug = lm.apply_env_override(config)
        assert slug == "tiny"
        assert config["whisper_model"] == "tiny"
        assert config["transcribe_backend"] == "faster_whisper"

def test_is_downloaded_logic():
    # Characterization of is_downloaded
    with patch("core.hub.model_weights_present", return_value=True):
        assert lm.is_downloaded({"model_path": "/fake/path"}) is True
    with patch("core.hub.model_weights_present", return_value=False):
        assert lm.is_downloaded({"model_path": "/fake/path"}) is False
