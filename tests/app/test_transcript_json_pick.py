"""The transcript JSON of a task is never the ``.chapters.json`` sidecar.

With output formats such as ["srt"] and auto-chapters on, the worker reports
``talk.srt`` and ``talk.chapters.json`` in ``task.output_paths``. Taking the
first ``.json`` entry made "View transcript", "Save shareable page" and the
word-count fallback read the chapters file as if it were the transcript.
"""
from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app import app as appmod
from app.domain import task_outputs
from app.services.transcription_service import TranscriptionService

SRT = "1\n00:00:00,000 --> 00:00:02,000\nHello world again\n\n"
CHAPTERS = [{"index": 0, "title": "Intro", "start": 0.0, "end": 9.0}]
SEGMENTS = [{"start": 0.0, "end": 2.0, "text": "Hello world again"}]


def _write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _srt_plus_chapters(tmp_path):
    """formats ["srt"] + auto-chapters: no transcript JSON, only the sidecar."""
    media = tmp_path / "talk.mp4"
    media.write_bytes(b"x")
    _write(tmp_path / "talk.srt", SRT)
    _write(tmp_path / "talk.chapters.json", json.dumps(CHAPTERS))
    return SimpleNamespace(
        file_path=str(media),
        output_paths=[str(tmp_path / "talk.srt"), str(tmp_path / "talk.chapters.json")],
        language="en", detected_language="en", word_count=0, audio_duration=0.0,
        whisper_task=None,
    )


def _json_plus_chapters(tmp_path):
    task = _srt_plus_chapters(tmp_path)
    _write(tmp_path / "talk.json", json.dumps(SEGMENTS))
    # The sidecar is listed BEFORE the transcript: order must not decide.
    task.output_paths = [
        str(tmp_path / "talk.srt"),
        str(tmp_path / "talk.chapters.json"),
        str(tmp_path / "talk.json"),
    ]
    return task


# --- the helper -----------------------------------------------------------


def test_is_sidecar_json_names_the_chapters_file_only():
    assert task_outputs.is_sidecar_json("a/talk.chapters.json")
    assert task_outputs.is_sidecar_json("a/talk (1).CHAPTERS.JSON")
    assert not task_outputs.is_sidecar_json("a/talk.json")
    assert not task_outputs.is_sidecar_json("a/talk (1).json")
    assert not task_outputs.is_sidecar_json("a/talk.srt")


def test_pick_ignores_the_chapters_sidecar_even_when_listed_first():
    paths = ["d/talk.chapters.json", "d/talk.srt", "d/talk (1).json"]
    assert task_outputs.pick_transcript_json(paths) == "d/talk (1).json"


def test_pick_prefers_the_exact_source_stem():
    paths = ["d/talk (1).json", "d/talk.json"]
    assert task_outputs.pick_transcript_json(paths, "d/talk.mp4") == "d/talk.json"
    assert task_outputs.pick_transcript_json(paths) == "d/talk (1).json"


def test_pick_returns_none_when_only_the_sidecar_or_non_json_exists():
    assert task_outputs.pick_transcript_json(["d/talk.chapters.json", "d/talk.srt"]) is None
    assert task_outputs.pick_transcript_json([]) is None
    assert task_outputs.pick_transcript_json(None) is None


def test_pick_keeps_a_transcript_whose_source_name_ends_in_chapters(tmp_path):
    """Source "talk.chapters.mp4" really writes "talk.chapters.json" as its transcript."""
    paths = ["d/talk.chapters.json"]
    assert (
        task_outputs.pick_transcript_json(paths, "d/talk.chapters.mp4")
        == "d/talk.chapters.json"
    )


def test_pick_must_exist_skips_missing_files(tmp_path):
    real = tmp_path / "talk (1).json"
    real.write_text("[]", encoding="utf-8")
    paths = [str(tmp_path / "talk.json"), str(real)]
    assert task_outputs.pick_transcript_json(paths, must_exist=True) == str(real)
    assert task_outputs.pick_transcript_json(paths) == str(tmp_path / "talk.json")


def test_task_transcript_json_reads_the_task(tmp_path):
    task = _json_plus_chapters(tmp_path)
    assert task_outputs.task_transcript_json(task) == str(tmp_path / "talk.json")
    assert task_outputs.task_transcript_json(SimpleNamespace(file_path="x.mp4")) is None


# --- site 1: App._task_json_output (queue menu, sample result) -------------


def test_task_json_output_skips_the_chapters_sidecar(tmp_path):
    task = _srt_plus_chapters(tmp_path)
    assert appmod.App._task_json_output(task) is None
    task = _json_plus_chapters(tmp_path)
    assert appmod.App._task_json_output(task) == str(tmp_path / "talk.json")


def test_sample_result_with_srt_and_chapters_opens_the_srt_not_the_sidecar(tmp_path):
    task = _srt_plus_chapters(tmp_path)
    fake = SimpleNamespace(
        _task_json_output=appmod.App._task_json_output,
        open_transcript_viewer_for=MagicMock(), _open_file=MagicMock(), log=MagicMock(),
    )
    appmod.App.open_sample_result(fake, task)  # type: ignore[arg-type]
    fake.open_transcript_viewer_for.assert_not_called()
    fake._open_file.assert_called_once_with(str(tmp_path / "talk.srt"))


def _viewer_fake(monkeypatch, answer):
    ask = MagicMock(return_value=answer)
    monkeypatch.setattr(appmod.messagebox, "askyesno", ask)
    opened = MagicMock()
    monkeypatch.setattr(appmod, "_open_transcript_viewer", opened)
    return ask, opened


def test_queue_view_transcript_without_a_json_explains_instead_of_a_bare_picker(tmp_path, monkeypatch):
    """srt-only run with chapters: the viewer reads .json only, so say why first."""
    task = _srt_plus_chapters(tmp_path)
    ask, opened = _viewer_fake(monkeypatch, False)
    fake = SimpleNamespace(_task_json_output=appmod.App._task_json_output)
    appmod.App.open_transcript_viewer_for(  # type: ignore[arg-type]
        fake, task.file_path, appmod.App._task_json_output(task), "en"
    )
    ask.assert_called_once()
    message = ask.call_args[0][1]
    assert "talk.mp4" in message and ".json" in message and "Whisper JSON" in message
    opened.assert_not_called()  # the answer was No: no picker either


def test_queue_view_transcript_can_still_pick_a_json_by_hand(tmp_path, monkeypatch):
    task = _srt_plus_chapters(tmp_path)
    ask, opened = _viewer_fake(monkeypatch, True)
    fake = SimpleNamespace()
    appmod.App.open_transcript_viewer_for(fake, task.file_path, None)  # type: ignore[arg-type]
    opened.assert_called_once_with(fake, None)


def test_queue_view_transcript_with_a_json_opens_it_without_asking(tmp_path, monkeypatch):
    task = _json_plus_chapters(tmp_path)
    ask, opened = _viewer_fake(monkeypatch, False)
    fake = SimpleNamespace()
    appmod.App.open_transcript_viewer_for(  # type: ignore[arg-type]
        fake, task.file_path, str(tmp_path / "talk.json"), "en"
    )
    ask.assert_not_called()
    assert opened.call_args[0][1] == str(tmp_path / "talk.json")


# --- site 2: the Last Result card's buttons --------------------------------


@pytest.fixture()
def tk_root():
    try:
        root = tk.Tk()
    except tk.TclError:  # pragma: no cover - headless box
        pytest.skip("no display")
    root.withdraw()
    yield root
    root.destroy()


def _buttons(widget):
    out = {}
    for child in widget.winfo_children():
        if isinstance(child, ttk.Button):
            out[str(child.cget("text"))] = child
        out.update(_buttons(child))
    return out


def _result_card(root, task):
    fake = SimpleNamespace(
        last_result_frame=ttk.Frame(root), last_result_empty_label=MagicMock(),
        last_result_body=ttk.Frame(root), tray=None, log=MagicMock(), nb=MagicMock(),
        t1=object(), app_config={}, chime_on_complete_var=None,
        _open_file=MagicMock(), _open_folder=MagicMock(),
        open_transcript_viewer_for=MagicMock(), _save_shareable_page_for=MagicMock(),
    )
    appmod.App.show_last_result(fake, task)  # type: ignore[arg-type]
    return fake


def test_last_result_card_gives_the_transcript_json_to_the_buttons(tk_root, tmp_path):
    task = _json_plus_chapters(tmp_path)
    fake = _result_card(tk_root, task)
    buttons = _buttons(fake.last_result_body)
    buttons["View transcript"].invoke()
    fake.open_transcript_viewer_for.assert_called_once_with(
        task.file_path, str(tmp_path / "talk.json"), "en"
    )
    buttons["Save shareable page"].invoke()
    assert fake._save_shareable_page_for.call_args[0][1] == str(tmp_path / "talk.json")


def test_last_result_card_has_no_viewer_buttons_for_srt_plus_chapters(tk_root, tmp_path):
    fake = _result_card(tk_root, _srt_plus_chapters(tmp_path))
    buttons = _buttons(fake.last_result_body)
    assert "View transcript" not in buttons
    assert "Save shareable page" not in buttons
    assert "Open folder" in buttons


# --- site 3: the word-count fallback ---------------------------------------


def test_stats_read_the_srt_not_the_chapters_sidecar(tmp_path):
    task = _srt_plus_chapters(tmp_path)
    service = TranscriptionService(SimpleNamespace(app_config={}))
    assert service._derive_transcript_stats(task) == (3, 2.0)


def test_stats_read_the_transcript_json_listed_after_the_sidecar(tmp_path):
    task = _json_plus_chapters(tmp_path)
    service = TranscriptionService(SimpleNamespace(app_config={}))
    assert service._derive_transcript_stats(task) == (3, 2.0)
