"""``gui.py transcribe --formats/--diarization`` apply to that run only.

Field report: one CLI run with ``--formats txt srt json`` rewrote the app's
saved ``output_formats`` in config.json (``['txt']`` became
``['txt', 'srt', 'json']``), silently changing the GUI's defaults.
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
    model_dir = tmp_path / "models" / "large-v3"
    model_dir.mkdir(parents=True)
    (model_dir / "model.bin").write_bytes(b"x")
    state: dict[str, Any] = {
        "cfg": {"output_formats": ["txt"], "diarization_enabled": False,
                "whisper_model": "large-v3", "model": {"name": "large-v3"},
                "model_path": str(model_dir)},
        "saved": [], "seen": {},
    }
    monkeypatch.setattr(config, "load_config", lambda: dict(state["cfg"]))
    monkeypatch.setattr(config, "save_config",
                        lambda cfg: state["saved"].append(dict(cfg)))
    monkeypatch.setattr(transcriber, "config", {})
    monkeypatch.setattr(transcriber, "load_existing_model", lambda cb=None: True)

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        state["seen"] = {
            "output_formats": transcriber.config.get("output_formats"),
            "diarization_enabled": transcriber.config.get("diarization_enabled"),
        }

    monkeypatch.setattr(transcriber, "transcribe", fake_transcribe)

    class _NoHistory:
        def __init__(self):
            raise RuntimeError("no history in this test")

    monkeypatch.setattr(history, "HistoryDB", _NoHistory)

    def run(*extra: str) -> int:
        args = gui._build_argparser().parse_args(["transcribe", str(src), *extra])
        return gui._cli_transcribe(args)

    state["run"] = run
    return state


def test_formats_and_diarization_reach_the_run_but_are_not_saved(cli):
    cli["run"]("--formats", "txt", "srt", "json", "--diarization")
    assert cli["seen"] == {
        "output_formats": ["txt", "srt", "json"], "diarization_enabled": True,
    }
    assert cli["saved"] == []


def test_plain_run_uses_and_keeps_the_saved_settings(cli):
    cli["run"]()
    assert cli["seen"] == {"output_formats": ["txt"], "diarization_enabled": False}
    assert cli["saved"] == []


def test_help_says_the_flags_are_not_saved():
    import gui

    sub = gui._build_argparser()._subparsers._group_actions[0]  # type: ignore[union-attr]
    helps = {a.dest: a.help for a in sub.choices["transcribe"]._actions}
    assert "not saved" in helps["formats"]
    assert "not saved" in helps["diarization"]
    assert "saved as the app's model" in helps["model"]
