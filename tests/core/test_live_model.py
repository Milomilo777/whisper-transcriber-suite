"""Live-tab model choice (core/live_model.py)."""
from __future__ import annotations

import pytest

from core import live_model as lm


def test_cpu_recommendation_by_language_and_cores():
    assert lm.recommended_cpu_slug("en", 8) == "small.en"
    assert lm.recommended_cpu_slug("en", 4) == "base.en"
    # base is too weak for non-English; small is the floor.
    assert lm.recommended_cpu_slug("fa", 2) == "small"
    assert lm.recommended_cpu_slug(None, 16) == "small"


@pytest.mark.parametrize("choice,device,expected", [
    ("auto", "cuda", None),        # GPU keeps the main model
    ("auto", "cpu", "small"),
    (None, "cpu", "tiny"),         # missing key -> the tiny default
    ("main", "cpu", None),
    ("medium", "cpu", "medium"),   # explicit pick wins everywhere
    ("medium", "cuda", "medium"),
])
def test_resolve_live_slug(choice, device, expected):
    cfg = {} if choice is None else {"live_model": choice}
    assert lm.resolve_live_slug(cfg, "fa", device) == expected


def test_live_model_config_points_at_the_hub(tmp_path):
    cfg = {"hub_folder": str(tmp_path), "whisper_model": "large-v3",
           "transcribe_backend": "cloud_stt"}
    out = lm.live_model_config(cfg, "small")
    assert out is not None
    assert out["whisper_model"] == "small"
    assert out["model_path"] == str(tmp_path / "models--Systran--faster-whisper-small")
    assert out["transcribe_backend"] == "faster_whisper"
    assert cfg["whisper_model"] == "large-v3"  # original untouched
    assert lm.live_model_config(cfg, "no-such-model") is None


def test_env_override_applies_only_a_downloaded_model(tmp_path, monkeypatch):
    cfg = {"hub_folder": str(tmp_path), "whisper_model": "large-v3",
           "model_path": "main-path", "transcribe_backend": "faster_whisper"}
    monkeypatch.delenv(lm.LIVE_MODEL_ENV, raising=False)
    assert lm.apply_env_override(cfg) is None

    monkeypatch.setenv(lm.LIVE_MODEL_ENV, "small")
    assert lm.apply_env_override(cfg) is None          # not on disk yet
    assert cfg["model_path"] == "main-path"

    folder = tmp_path / "models--Systran--faster-whisper-small"
    folder.mkdir()
    (folder / "model.bin").write_bytes(b"x")
    assert lm.apply_env_override(cfg) == "small"
    assert cfg["model_path"] == str(folder)
    assert cfg["whisper_model"] == "small"


def test_transcriber_passes_the_model_to_the_worker_env(monkeypatch):
    from app.services import live_service

    seen: dict = {}

    class _Stop(Exception):
        pass

    def fake_popen(cmd, **kw):
        seen.update(kw["env"])
        raise OSError("stop here")

    monkeypatch.setattr(live_service.subprocess, "Popen", fake_popen)
    monkeypatch.setenv(lm.LIVE_MODEL_ENV, "stale-from-parent")
    with pytest.raises(live_service.LiveWorkerError):
        live_service.LiveTranscriber("gui.py", model_slug="small").start()
    assert seen[lm.LIVE_MODEL_ENV] == "small"
    seen.clear()
    with pytest.raises(live_service.LiveWorkerError):
        live_service.LiveTranscriber("gui.py").start()
    assert lm.LIVE_MODEL_ENV not in seen   # main model: no stale override
