"""A ``.whisperproject.json`` may only change per-file transcription choices.

The file is found by walking up from the media file, so it can arrive inside a
downloaded or shared folder. Before the allow-list it could set any config key:
``llm_remote_base_url`` + ``ai_enabled`` sent transcripts and the user's API key
(as a Bearer token) to another host, ``transcribe_backend`` sent the audio to a
cloud engine on the user's key, and ``stats_url`` / ``server_webhook_url``
redirected the app's own uploads.
"""
from __future__ import annotations

import json
import logging

import pytest

import core.config as cfg
import core.transcriber as t
from core import llm
from core.config import (
    DEFAULT_CONFIG,
    LOCAL_ONLY_KEYS,
    PROJECT_ALLOWED_KEYS,
    PROJECT_FILE_NAME,
    load_project_overrides,
    merge_project_overrides,
)
from core.server.httpd import _OPTION_SPEC
from core.task import TranscriptionTask

# Keys that move audio, transcripts or secrets off the PC, point the app at
# another host, a program or a folder, or change app-level state.
_HOSTILE = {
    "llm_remote_base_url": "https://attacker.example/v1",
    "llm_provider": "remote",
    "llm_remote_model": "x",
    "llm_remote_api_key": "dummy-credential-B",
    "ai_enabled": True,
    "ai_model_path": "C:/elsewhere/model.gguf",
    "transcribe_backend": "cloud_stt",
    "cloud_stt_api_key": "dummy-credential-B",
    "gcloud_stt_credentials_json": "C:/elsewhere/key.json",
    "gcloud_stt_bucket": "someone-elses-bucket",
    "stats_url": "https://attacker.example/stats",
    "config_url": "https://attacker.example/app_config.json",
    "server_webhook_url": "https://attacker.example/hook",
    "server_share_lan": True,
    "server_token": "dummy-credential-C",
    "telemetry_opt_in": True,
    "work_offline": False,
    "cookies_from_browser": "chrome",
    "model": {"name": "tiny", "url": "https://attacker.example/model.zip"},
    "model_catalog": {"tiny": {"url": "https://attacker.example/m.zip"}},
    "model_path": "C:/elsewhere/model",
    "whisper_model": "tiny",
    "hub_folder": "C:/elsewhere",
    "download_folder": "C:/elsewhere",
    "subtitle_edit_path": "C:/elsewhere/run.exe",
    "output_filename_template": "../../{base}.{ext}",
    "device": "cuda",
    "some_future_key": 1,
}

# One valid value per allowed key.
_ALLOWED = {
    "output_formats": ["srt", "txt"],
    "initial_prompt": "Glossary: Anthropic.",
    "hotwords": "Anthropic",
    "word_timestamps": True,
    "batch_size": 8,
    "vad_enabled": False,
    "vad_threshold": 0.4,
    "vad_min_silence_ms": 300,
    "vad_speech_pad_ms": 200,
    "vad_window_s": 20,
    "hallucination_detect_enabled": False,
    "demucs_enabled": True,
    "denoise_enabled": True,
    "denoise_level": "light",
    "diarization_enabled": True,
    "diarization_num_speakers": 2,
    "diarization_cluster_threshold": 0.6,
    "alignment": "stable_ts",
    "auto_chapters_enabled": False,
    "chapter_min_seconds": 90.0,
    "chapter_gap_seconds": 3.0,
}


def _write(folder, data):
    (folder / PROJECT_FILE_NAME).write_text(json.dumps(data), encoding="utf-8")
    media = folder / "a.wav"
    media.write_bytes(b"x")
    return media


@pytest.fixture(autouse=True)
def _fresh_refusal_log():
    cfg._REFUSED_OVERRIDES_LOGGED.clear()
    yield
    cfg._REFUSED_OVERRIDES_LOGGED.clear()


def test_allowed_file_is_kept_whole(tmp_path):
    media = _write(tmp_path, _ALLOWED)
    assert load_project_overrides(str(media)) == _ALLOWED


def test_test_table_covers_the_whole_allow_list():
    assert set(_ALLOWED) == set(PROJECT_ALLOWED_KEYS)


@pytest.mark.parametrize("key", sorted(_HOSTILE))
def test_each_refused_key_is_dropped(tmp_path, key):
    media = _write(tmp_path, {key: _HOSTILE[key]})
    assert load_project_overrides(str(media)) == {}


def test_mixed_file_keeps_allowed_and_drops_refused(tmp_path):
    media = _write(tmp_path, {**_HOSTILE, "hotwords": "Anthropic",
                              "word_timestamps": True})
    assert load_project_overrides(str(media)) == {
        "hotwords": "Anthropic", "word_timestamps": True,
    }


def test_refused_keys_logged_once_with_path_and_no_values(tmp_path, caplog):
    media = _write(tmp_path, {"llm_remote_api_key": "dummy-credential-B",
                              "stats_url": "https://attacker.example/stats",
                              "hotwords": "Anthropic"})
    with caplog.at_level(logging.WARNING, logger=cfg.logger.name):
        for _ in range(3):  # several files in the folder, two loads per file
            load_project_overrides(str(media))
    refused = [r.getMessage() for r in caplog.records
               if "llm_remote_api_key" in r.getMessage()]
    assert len(refused) == 1
    message = refused[0]
    assert str(tmp_path / PROJECT_FILE_NAME) in message
    assert "stats_url" in message
    assert "hotwords" not in message
    # The values (a key, a URL) never reach the log.
    assert "dummy-credential-B" not in caplog.text
    assert "attacker.example" not in caplog.text


def test_changed_refused_set_is_logged_again(tmp_path, caplog):
    media = _write(tmp_path, {"stats_url": "https://attacker.example/stats"})
    with caplog.at_level(logging.WARNING, logger=cfg.logger.name):
        load_project_overrides(str(media))
        _write(tmp_path, {"server_webhook_url": "https://attacker.example/h"})
        load_project_overrides(str(media))
    text = caplog.text
    assert "stats_url" in text and "server_webhook_url" in text


def test_refusal_log_survives_hostile_key_names(tmp_path, caplog):
    keys = {("k%03d" % i) + "\n" + "x" * 500: 1 for i in range(50)}
    media = _write(tmp_path, keys)
    with caplog.at_level(logging.WARNING, logger=cfg.logger.name):
        assert load_project_overrides(str(media)) == {}
    message = [r.getMessage() for r in caplog.records][-1]
    assert "\n" not in message
    assert len(message) < 4000


def test_project_file_cannot_send_transcripts_or_key_elsewhere(tmp_path):
    """The review repro: the user's own key must never meet another host."""
    media = _write(tmp_path, {
        "llm_remote_base_url": "https://attacker.example/v1", "ai_enabled": True,
        "llm_provider": "remote", "llm_remote_model": "x",
        "auto_chapters_enabled": True,
    })
    user = {"ai_enabled": False, "llm_provider": "local",
            "llm_remote_api_key": "dummy-credential-A",
            "llm_remote_base_url": "https://api.openai.com/v1"}
    merged = merge_project_overrides(user, str(media))
    assert merged["llm_remote_base_url"] == "https://api.openai.com/v1"
    assert llm.build_runner_from_config(merged) is None


def test_engine_scope_ignores_refused_keys(monkeypatch, tmp_path):
    """The real consumer: the per-file override scope in the transcriber."""
    media = _write(tmp_path, {"transcribe_backend": "cloud_stt",
                              "stats_url": "https://attacker.example/stats",
                              "hotwords": "Anthropic"})
    monkeypatch.setattr(t, "config", {"transcribe_backend": "faster_whisper",
                                      "stats_url": "https://stats.example/",
                                      "hotwords": ""})
    monkeypatch.setattr(t, "load_config", lambda: {})
    with t._runtime_overrides_scope(TranscriptionTask(str(media))):
        assert t.config["transcribe_backend"] == "faster_whisper"
        assert t.config["stats_url"] == "https://stats.example/"
        assert t.config["hotwords"] == "Anthropic"
    assert t.config["hotwords"] == ""


def test_every_web_job_option_is_allowed():
    """The server writes per-job options into a .whisperproject.json; a new
    option missing from the allow-list would be dropped silently."""
    for key, _kind in _OPTION_SPEC:
        assert key in PROJECT_ALLOWED_KEYS, key


def test_allow_list_holds_no_off_pc_or_app_level_key():
    for key in PROJECT_ALLOWED_KEYS:
        assert key not in LOCAL_ONLY_KEYS, key
        for word in ("url", "key", "token", "path", "folder", "backend",
                     "webhook", "stats", "cookie", "llm", "ai_", "server",
                     "cloud", "gcloud", "nvidia", "telemetry", "model",
                     "template", "device"):
            assert word not in key, (key, word)
        default = DEFAULT_CONFIG.get(key, "none")
        assert isinstance(default, (bool, int, float, str, list)), key
