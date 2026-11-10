"""Named presets contain only explicitly permitted transcription settings."""
import json

import pytest

from core.presets import PresetStore, capture_settings


def test_capture_keeps_safe_settings_and_rejects_secrets():
    result = capture_settings({"vad_enabled": False, "batch_size": 12,
                               "api_key": "private", "device": "cuda",
                               "model": {"name": "large"}, "webhook_url": "private"})
    assert result == {"vad_enabled": False, "batch_size": 12}


def test_roundtrip_replace_delete_and_isolation(tmp_path):
    store = PresetStore(tmp_path / "presets.json")
    store.save("Interview", {"vad_enabled": False, "output_formats": ["srt"]})
    assert PresetStore(store.path).load()["Interview"]["vad_enabled"] is False
    with pytest.raises(ValueError):
        store.save("Interview", {"vad_enabled": True})
    store.save("Interview", {"vad_enabled": True}, replace=True)
    assert store.load()["Interview"] == {"vad_enabled": True}
    store.delete("Interview")
    assert store.load() == {}


def test_bad_file_is_preserved(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text("broken", encoding="utf-8")
    with pytest.raises(ValueError):
        PresetStore(path).save("New", {"vad_enabled": True})
    assert path.read_text() == "broken"


def test_untrusted_file_is_filtered_and_values_validated(tmp_path):
    path = tmp_path / "presets.json"
    path.write_text(json.dumps({"version": 1, "presets": {"Test": {
        "api_key": "private", "batch_size": True, "vad_threshold": 9,
        "output_formats": ["srt", "../../bad"], "diarization_enabled": "yes",
        "vad_enabled": False}}}), encoding="utf-8")
    assert PresetStore(path).load() == {"Test": {"vad_enabled": False}}


@pytest.mark.parametrize("name", ["", " ", "a\nb", "a" * 81])
def test_invalid_names(tmp_path, name):
    with pytest.raises(ValueError):
        PresetStore(tmp_path / "presets.json").save(name, {})


def test_interrupted_write_preserves_previous_presets(monkeypatch, tmp_path):
    from core import presets
    store = PresetStore(tmp_path / "presets.json")
    store.save("Original", {"vad_enabled": False})
    original = store.path.read_bytes()
    def fail_write(*_args):
        raise OSError("simulated disk failure")
    monkeypatch.setattr(presets, "_write_text_atomic", fail_write)
    with pytest.raises(OSError):
        store.save("New", {"vad_enabled": True})
    assert store.path.read_bytes() == original


def test_concurrent_saves_and_unicode_roundtrip(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = PresetStore(tmp_path / "presets.json")
    names = ["Interview", "\u0645\u0635\u0627\u062d\u0628\u0647"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda name: store.save(name, {"initial_prompt": "\u0633\u0644\u0627\u0645"}), names))
    assert set(store.load()) == set(names)
    assert all(settings["initial_prompt"] == "\u0633\u0644\u0627\u0645" for settings in store.load().values())
