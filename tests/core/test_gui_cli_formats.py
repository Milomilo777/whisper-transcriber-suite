"""Regression for the CLI transcribe parser's format choices.

The GUI/CLI format registry includes ``smtv_docx`` via
``core.writers.supported_formats``. The transcribe subcommand must accept the
same registry entry, otherwise a user cannot request the SMTV output from the
command line even though the writer exists and the Advanced dialog shows it.
"""
from __future__ import annotations


def test_transcribe_parser_accepts_smtv_docx():
    import gui

    parser = gui._build_argparser()
    args = parser.parse_args([
        "transcribe",
        r"E:\3025-NWN-Daily-Scroll-2m_0001.mp4",
        "--formats",
        "smtv_docx",
    ])
    assert args.formats == ["smtv_docx"]


def test_cli_transcribe_reports_real_output_paths(monkeypatch, tmp_path, capsys):
    import gui
    import core.config as config
    import core.history as history
    import core.transcriber as transcriber

    src = tmp_path / "clip.mp4"
    src.write_bytes(b"video")
    out1 = tmp_path / "clip (1).srt"
    out2 = tmp_path / "clip (1).json"
    out3 = tmp_path / "clip (1).docx"
    out4 = tmp_path / "clip -Transcription in English \u2013 Translation in English (1).docx"
    for path in (out1, out2, out3, out4):
        path.write_bytes(b"x")

    monkeypatch.setattr(
        config,
        "load_config",
        lambda: {
            "output_formats": ["srt", "json", "docx", "smtv_docx"],
            "model": {"name": "demo"},
        },
    )
    monkeypatch.setattr(config, "save_config", lambda _cfg: None)
    monkeypatch.setattr(transcriber, "load_existing_model", lambda _cb=None: True)

    def fake_transcribe(task, progress_cb, log_cb, language_cb=None):
        task.output_paths = [str(out1), str(out2), str(out3), str(out4)]
        task.detected_language = "en"
        progress_cb(35)
        progress_cb(98)

    monkeypatch.setattr(transcriber, "transcribe", fake_transcribe)

    class _DummyHistory:
        def __init__(self):
            self.finished = None
            self.inserted = None

        def insert_transcription(self, *args, **kwargs):
            self.inserted = (args, kwargs)
            return 42

        def finish_transcription(self, *args, **kwargs):
            self.finished = (args, kwargs)

        def close(self):
            pass

    monkeypatch.setattr(history, "HistoryDB", _DummyHistory)

    exit_code = gui._cli_transcribe(
        gui._build_argparser().parse_args([
            "transcribe",
            str(src),
            "--formats",
            "srt",
            "json",
            "docx",
            "smtv_docx",
        ])
    )
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "progress 35%" in captured
    assert "progress 98%" in captured
    assert "wrote 4 output(s)" in captured
    assert "clip (1).srt" in captured
    assert "clip -Transcription in English" in captured


def test_cli_does_not_attach_existing_outputs_to_failed_run(monkeypatch, tmp_path):
    import gui
    from core import config, history, transcriber

    source = tmp_path / "recording.wav"
    source.touch()
    stale = source.with_suffix(".srt")
    stale.write_text("existing transcript", encoding="utf-8")
    finish_calls = []

    class History:
        def insert_transcription(self, *_args, **_kwargs):
            return 42

        def finish_transcription(self, *_args, **kwargs):
            finish_calls.append(kwargs["output_paths"])

        def close(self):
            pass

    def fail(*_args, **_kwargs):
        raise RuntimeError("test decoding error")

    monkeypatch.setattr(config, "load_config", lambda: {"output_formats": ["srt"]})
    monkeypatch.setattr(transcriber, "config", {})
    monkeypatch.setattr(transcriber, "load_existing_model", lambda _callback: True)
    monkeypatch.setattr(transcriber, "transcribe", fail)
    monkeypatch.setattr(history, "HistoryDB", History)
    args = gui._build_argparser().parse_args(["transcribe", str(source)])

    assert gui._cli_transcribe(args) == 4
    assert finish_calls == [[]]
    assert stale.read_text(encoding="utf-8") == "existing transcript"
