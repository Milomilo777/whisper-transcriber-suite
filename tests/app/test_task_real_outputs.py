"""Actions on a finished task use the files the job really wrote.

A re-run writes ``name (1).srt`` / ``name (1).json`` and an output template
can move the outputs, so burn-in, the oTranscribe export, the transcript
viewer, "Open folder" and the stats fallback must read ``task.output_paths``
(or the run's real stem) instead of recomputing ``<source>.<ext>``. They must
also never replace a file the user may have edited without asking.
"""
from __future__ import annotations

import json
import os
from types import SimpleNamespace

import pytest

from app import app as appmod
from app.dialogs import transcript_viewer as tv
from app.domain import task_outputs
from app.services import integrations_service as integ
from app.services.transcription_service import TranscriptionService

SRT = "1\n00:00:00,000 --> 00:00:01,000\n{}\n\n"


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _rerun_task(tmp_path):
    """A source whose first run wrote talk.srt and whose re-run wrote talk (1).srt."""
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"x")
    _write(tmp_path / "talk.srt", SRT.format("OLD run 1"))
    _write(tmp_path / "talk (1).srt", SRT.format("NEW run 2"))
    _write(tmp_path / "talk (1).json", "[]")
    return SimpleNamespace(
        file_path=str(media),
        output_paths=[str(tmp_path / "talk (1).srt"), str(tmp_path / "talk (1).json")],
        language="en", detected_language="en",
    )


# --- task_outputs helpers -------------------------------------------------


def test_task_srt_output_prefers_the_written_file(tmp_path):
    task = _rerun_task(tmp_path)
    assert task_outputs.task_srt_output(task) == str(tmp_path / "talk (1).srt")


def test_task_srt_output_falls_back_to_the_source_stem(tmp_path):
    task = _rerun_task(tmp_path)
    task.output_paths = None
    assert task_outputs.task_srt_output(task) == str(tmp_path / "talk.srt")
    os.remove(tmp_path / "talk.srt")
    assert task_outputs.task_srt_output(task) is None


def test_task_srt_output_skips_a_listed_file_that_is_gone(tmp_path):
    task = _rerun_task(tmp_path)
    os.remove(tmp_path / "talk (1).srt")
    assert task_outputs.task_srt_output(task) == str(tmp_path / "talk.srt")


def test_task_output_folder_is_where_the_outputs_are(tmp_path):
    out_dir = tmp_path / "subs"
    out_dir.mkdir()
    _write(out_dir / "talk.srt", SRT.format("x"))
    task = SimpleNamespace(
        file_path=str(tmp_path / "talk.mp4"), output_paths=[str(out_dir / "talk.srt")]
    )
    assert task_outputs.task_output_folder(task) == str(out_dir)
    task.output_paths = []
    assert task_outputs.task_output_folder(task) == str(tmp_path)


# --- burn subtitles (S06-4) -----------------------------------------------


def test_burn_uses_the_srt_the_rerun_wrote(tmp_path, monkeypatch):
    task = _rerun_task(tmp_path)
    burned: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        "core.burn_subs.burn", lambda src, srt, out: burned.append((src, srt, out))
    )
    monkeypatch.setattr("core._threads.safe_thread", lambda fn, **k: fn())
    monkeypatch.setattr(
        appmod.filedialog, "asksaveasfilename", lambda **k: str(tmp_path / "out.mp4")
    )
    fake = SimpleNamespace(log=lambda m: None, post_to_main=lambda f: None)
    appmod.App._burn_subs_for(fake, task)  # type: ignore[arg-type]
    assert burned == [(task.file_path, str(tmp_path / "talk (1).srt"), str(tmp_path / "out.mp4"))]


def test_burn_with_no_srt_on_disk_warns_and_does_not_burn(tmp_path, monkeypatch):
    task = _rerun_task(tmp_path)
    task.output_paths = [str(tmp_path / "talk (1).json")]
    os.remove(tmp_path / "talk.srt")
    warned: list[str] = []
    monkeypatch.setattr(appmod.messagebox, "showwarning", lambda t, m, **k: warned.append(t))
    monkeypatch.setattr(
        "core.burn_subs.burn", lambda *a: pytest.fail("burn must not run")
    )
    fake = SimpleNamespace(log=lambda m: None, post_to_main=lambda f: None)
    appmod.App._burn_subs_for(fake, task)  # type: ignore[arg-type]
    assert warned == ["No SRT found"]


# --- oTranscribe export (S11-10) ------------------------------------------


class _FakeApp:
    def __init__(self):
        self.logs: list[str] = []
        self.status_var = SimpleNamespace(set=lambda s: None)

    def log(self, m):
        self.logs.append(m)


def test_otr_export_reads_the_rerun_srt_and_writes_beside_it(tmp_path):
    task = _rerun_task(tmp_path)
    integ.IntegrationsService(_FakeApp()).export_task_to_otr(task)  # type: ignore[arg-type]
    otr = tmp_path / "talk (1).otr"
    payload = json.loads(otr.read_text(encoding="utf-8"))
    assert "NEW run 2" in payload["text"]
    assert payload["media"] == "talk.mp4"
    assert b"\r\n" not in otr.read_bytes()
    assert not (tmp_path / "talk.otr").exists()


@pytest.mark.parametrize(
    "answer, expect_replaced, expect_new", [(True, True, False), (False, False, True), (None, False, False)]
)
def test_otr_export_asks_before_replacing_an_edited_file(
    tmp_path, monkeypatch, answer, expect_replaced, expect_new
):
    task = _rerun_task(tmp_path)
    edited = tmp_path / "talk (1).otr"
    _write(edited, '{"text": "USER EDITED IN OTRANSCRIBE"}')
    asked: list[str] = []
    monkeypatch.setattr(
        integ.messagebox, "askyesnocancel", lambda t, m, **k: asked.append(t) or answer
    )
    integ.IntegrationsService(_FakeApp()).export_task_to_otr(task)  # type: ignore[arg-type]
    assert asked == ["Replace .otr file?"]
    replaced = "USER EDITED" not in edited.read_text(encoding="utf-8")
    assert replaced is expect_replaced
    assert (tmp_path / "talk (1) (1).otr").exists() is expect_new


def test_otr_export_failure_leaves_the_old_file_intact(tmp_path, monkeypatch):
    task = _rerun_task(tmp_path)
    edited = tmp_path / "talk (1).otr"
    _write(edited, "ORIGINAL")
    monkeypatch.setattr(integ.messagebox, "askyesnocancel", lambda *a, **k: True)
    monkeypatch.setattr(integ, "show_error", lambda *a, **k: None)

    def boom(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(integ.os, "replace", boom)
    integ.IntegrationsService(_FakeApp()).export_task_to_otr(task)  # type: ignore[arg-type]
    assert edited.read_text(encoding="utf-8") == "ORIGINAL"
    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".part")] == []


# --- transcript viewer media pairing (S09-1) ------------------------------


@pytest.mark.parametrize(
    "ext", [".opus", ".mov", ".m4v", ".avi", ".wma", ".ts", ".mp4", ".MP4"]
)
def test_viewer_pairs_every_common_media_extension(tmp_path, ext):
    media = tmp_path / ("clip" + ext)
    media.write_bytes(b"x")
    found = tv._find_media_next_to(str(tmp_path / "clip.json"))
    assert found is not None and os.path.basename(found) == "clip" + ext


@pytest.mark.parametrize(
    "json_name", ["talk (1).json", "talk.en-translated.json", "talk.en-translated (2).json"]
)
def test_viewer_pairs_rerun_and_translated_outputs_with_the_source(tmp_path, json_name):
    (tmp_path / "talk.mp4").write_bytes(b"x")
    found = tv._find_media_next_to(str(tmp_path / json_name))
    assert found == str(tmp_path / "talk.mp4")


def test_viewer_prefers_media_with_the_exact_json_stem(tmp_path):
    (tmp_path / "talk.mp4").write_bytes(b"x")
    (tmp_path / "talk (1).mp4").write_bytes(b"x")
    assert tv._find_media_next_to(str(tmp_path / "talk (1).json")) == str(tmp_path / "talk (1).mp4")


def test_viewer_finds_nothing_for_unrelated_media(tmp_path):
    (tmp_path / "other.mp4").write_bytes(b"x")
    assert tv._find_media_next_to(str(tmp_path / "talk (1).json")) is None


def test_open_viewer_passes_the_task_source_as_media(tmp_path, monkeypatch):
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    json_path = out_dir / "renamed.json"
    _write(json_path, "[]")
    media = tmp_path / "talk.mov"
    media.write_bytes(b"x")
    opened: list[dict] = []
    monkeypatch.setattr(tv, "TranscriptViewer", lambda master, jp, **k: opened.append(dict(k, json=jp)))
    tv.open_viewer(None, str(json_path), media_path=str(media))  # type: ignore[arg-type]
    tv.open_viewer(None, str(json_path), media_path=str(tmp_path / "gone.mp4"))  # type: ignore[arg-type]
    assert opened[0]["media_path"] == str(media)
    # A source that is gone falls back to the viewer's own pairing.
    assert opened[1]["media_path"] is None


def test_app_view_transcript_hands_over_the_source(tmp_path, monkeypatch):
    task = _rerun_task(tmp_path)
    calls: list[tuple] = []
    monkeypatch.setattr(appmod, "_open_transcript_viewer", lambda *a, **k: calls.append((a, k)))
    appmod.App.open_transcript_viewer_for(
        SimpleNamespace(), task.file_path, task.output_paths[1], "en"  # type: ignore[arg-type]
    )
    (_master, json_path), kwargs = calls[0]
    assert json_path == task.output_paths[1]
    assert kwargs["media_path"] == task.file_path


# --- stats fallback for a translate run (S03-15) --------------------------


def test_stats_fallback_reads_the_translated_json(tmp_path):
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"x")
    with open(tmp_path / "talk.en-translated.json", "w", encoding="utf-8") as f:
        json.dump([{"start": 0.0, "end": 2.0, "text": "one two three"}], f)
    task = SimpleNamespace(output_paths=[], file_path=str(media), whisper_task="translate")
    service = TranscriptionService(SimpleNamespace(app_config={}))  # type: ignore[arg-type]
    assert service._derive_transcript_stats(task) == (3, 2.0)
    task.whisper_task = "transcribe"
    assert service._derive_transcript_stats(task) == (0, 0.0)
