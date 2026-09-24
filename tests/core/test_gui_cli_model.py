"""CLI ``transcribe --model`` + first-run model download.

The headless CLI used to have no way to pick a model and no way to download
one: a fresh install failed with "error: model not loaded" (open issue #6 in
docs/MACOS_BUILD_NOTES.md).
"""
from __future__ import annotations

from typing import Any

import pytest


@pytest.fixture
def cli(monkeypatch, tmp_path):
    import gui
    import core.config as config
    import core.history as history
    import core.transcriber as transcriber

    src = tmp_path / "clip.wav"
    src.write_bytes(b"audio")
    state: dict[str, Any] = {
        "cfg": {"output_formats": ["srt"], "whisper_model": "large-v3",
                "model": {"name": "large-v3"},
                "model_path": str(tmp_path / "models" / "large-v3")},
        "saved": [], "calls": [],
    }

    def _load_config():
        cfg = dict(state["cfg"])
        if not cfg.get("model_path"):
            # load_config() re-resolves an empty model_path to the model's folder.
            cfg["model_path"] = str(tmp_path / "models" / cfg["model"]["name"])
        return cfg

    def _save_config(cfg):
        state["saved"].append(dict(cfg))
        state["cfg"] = dict(cfg)

    monkeypatch.setattr(config, "load_config", _load_config)
    monkeypatch.setattr(config, "save_config", _save_config)
    monkeypatch.setattr(transcriber, "config", {})

    def _existing(cb=None):
        state["calls"].append("load_existing_model")
        return True

    def _download(status_cb=None, progress_cb=None, cancel_event=None):
        state["calls"].append("load_model")
        if progress_cb:
            progress_cb({"phase": "download", "percent": 50})
        return True

    monkeypatch.setattr(transcriber, "load_existing_model", _existing)
    monkeypatch.setattr(transcriber, "load_model", _download)
    monkeypatch.setattr(transcriber, "transcribe", lambda *a, **k: None)

    class _NoHistory:
        def __init__(self):
            raise RuntimeError("no history in this test")

    monkeypatch.setattr(history, "HistoryDB", _NoHistory)

    def run(*extra: str) -> int:
        args = gui._build_argparser().parse_args(["transcribe", str(src), *extra])
        return gui._cli_transcribe(args)

    state["run"] = run
    state["tmp"] = tmp_path
    return state


def test_missing_model_is_downloaded_instead_of_failing(cli, capsys):
    assert cli["run"]() == 0
    assert cli["calls"] == ["load_model"]
    out = capsys.readouterr().out
    assert "not downloaded yet" in out and "about 3 GB" in out
    assert "download 50%" in out


def test_present_model_is_loaded_without_download(cli):
    model_dir = cli["tmp"] / "models" / "large-v3"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"x")
    assert cli["run"]() == 0
    assert cli["calls"] == ["load_existing_model"]


def test_model_flag_switches_and_saves_the_model(cli, capsys):
    assert cli["run"]("--model", "small") == 0
    assert cli["saved"][0]["whisper_model"] == "small"
    assert cli["saved"][0]["model"]["name"]  # resolved catalog entry
    assert cli["saved"][0]["model_path"] == ""  # re-resolved for the new model
    assert "about 500 MB" in capsys.readouterr().out


def test_unknown_model_is_a_usage_error_listing_the_choices(cli, capsys):
    assert cli["run"]("--model", "gigantic") == 2
    err = capsys.readouterr().err
    assert "unknown model 'gigantic'" in err and "large-v3" in err
    assert cli["calls"] == []
