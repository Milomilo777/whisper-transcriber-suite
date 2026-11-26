"""Comparison reruns use indexed outputs and retain the original transcript."""
from __future__ import annotations

import os
import time
from types import SimpleNamespace

import pytest

from app import app as app_module
from app.dialogs import transcript_viewer
from app.services.transcription_service import TranscriptionService, transcribe_command
from core import segment_ops
from core.history import HistoryDB
from core.presets import PresetStore


def test_comparison_groups_one_to_many_and_retains_unmatched_cues():
    old = [{"start": 0, "end": 4, "text": "Old"},
           {"start": 6, "end": 7, "text": "Only old"}]
    new = [{"start": 0, "end": 2, "text": "New first"},
           {"start": 2, "end": 4, "text": "New second"},
           {"start": 8, "end": 9, "text": "Only new"}]
    assert [(part.start, part.original, part.result) for part in segment_ops.compare_time_blocks(old, new)] == [
        (0, "Old", "New first\nNew second"), (6, "Only old", ""), (8, "", "Only new"),
    ]


def test_long_cue_stays_aligned_with_every_overlapping_cue():
    old = [{"start": 0, "end": 90, "text": "Continuous"}]
    new = [{"start": i, "end": i + 30, "text": str(i)} for i in (0, 30, 60)]
    blocks = segment_ops.compare_time_blocks(old, new)
    assert [(block.original, block.result) for block in blocks] == [
        ("Continuous", "0\n30\n60"),
    ]


def test_comparison_checks_the_preset_language_before_worker_readiness(tmp_path, monkeypatch):
    media = tmp_path / "sample.wav"
    media.touch()
    checked = []
    fake = SimpleNamespace(
        queue=[], app_config={"whisper_model": "tiny.en"},
        _same_job_active=lambda task: False,
        _confirm_english_only_model=lambda **kw: checked.append(kw) or False,
        _ensure_transcribe_ready=lambda: False,
    )
    monkeypatch.setattr(app_module, "show_error", lambda *a, **k: None)
    assert not app_module.App.queue_transcript_comparison(
        fake, str(media), str(tmp_path / "sample.json"), {"language": "Persian"},
    )
    assert checked and checked[0]["language_override"] == "fa"
    assert not fake.queue


def test_queue_comparison_preserves_source_and_freezes_preset(tmp_path, monkeypatch):
    media = tmp_path / "شیوه.wav"
    media.write_bytes(b"media")
    source = tmp_path / "شیوه.json"
    source.write_bytes(b"original")
    changed = []
    def boom(*args, **kwargs):
        raise AssertionError("missing media must stop before worker readiness")
    fake = SimpleNamespace(
        queue=[], app_config={"output_formats": ["txt"], "word_timestamps": False},
        _ensure_transcribe_ready=lambda: True, _same_job_active=lambda task: False,
        _confirm_english_only_model=lambda **kwargs: True,
        _selected_transcribe_language=lambda: None,
        show_task_in_queue=changed.append, refresh=lambda: None,
    )
    monkeypatch.setattr(app_module, "show_error", lambda *a, **k: None)
    assert app_module.App.queue_transcript_comparison(
        fake, str(media), str(source), {"word_timestamps": True, "output_formats": ["md"]},
    )
    task = fake.queue[0]
    assert changed == [task]
    assert task.comparison_source == str(source)
    assert task.task_settings["word_timestamps"] is True
    assert task.output_formats == ["md", "json"]
    assert fake.app_config["word_timestamps"] is False
    assert source.read_bytes() == b"original"
    fake._ensure_transcribe_ready = boom
    assert not app_module.App.queue_transcript_comparison(fake, str(tmp_path / "missing.wav"), str(source), {})
    assert fake.queue == [task]
    assert source.read_bytes() == b"original"


@pytest.mark.parametrize(("cues", "track", "recorded_in"), [
    ([{"audio_track": 1}, {"audio_track": 1}], 1, None),
    ([{"audio_track": 0}], 0, None),
    ([{"audio_track": 1}, {}], 1, None),
    ([{"audio_track": 1}, {"audio_track": 0}], None, None),
    ([{"audio_track": 1, "audio_repaired": True}], None, None),
    ([{"audio_track": True}], None, None),
    ([{"text": "Legacy transcript"}], None, None),
    ([], 1, "queue"),
    ([], 1, "history"),
    ([], 1, "history aliases"),
])
def test_viewer_comparison_reruns_the_original_audio_track(
    tmp_path, monkeypatch, cues, track, recorded_in,
):
    media = tmp_path / "گفتار دو ترک.mkv"
    media.touch()
    source_json = media.with_suffix(".json")
    source_json.write_text("[]", encoding="utf-8")
    selected = []
    app = SimpleNamespace(
        queue=[], app_config={}, history=None,
        _same_job_active=lambda task: selected.append(task.audio_track) or False,
        _confirm_english_only_model=lambda **kwargs: True,
        _ensure_transcribe_ready=lambda: True,
        _selected_transcribe_language=lambda: None,
        refresh=lambda: None,
        show_task_in_queue=lambda task: None,
    )
    app.queue_transcript_comparison = lambda *args, **kwargs: (
        app_module.App.queue_transcript_comparison(app, *args, **kwargs)
    )
    app.comparison_audio_track = lambda *args: app_module.App.comparison_audio_track(app, *args)
    viewer = SimpleNamespace(
        _comparison_media_path=str(media), _app_config=lambda: app.app_config,
        master=app, json_path=str(source_json), segments=cues,
    )
    if recorded_in == "history aliases":
        for path, attribute in ((media, "_comparison_media_path"), (source_json, "json_path")):
            alias = path.with_suffix(path.suffix.upper())
            if not alias.exists():
                os.link(path, alias)
            setattr(viewer, attribute, str(alias))
    monkeypatch.setattr(PresetStore, "load", lambda store: {})
    monkeypatch.setattr(transcript_viewer, "ComparisonPresetDialog",
                        lambda *args: SimpleNamespace(result=0))

    with HistoryDB(tmp_path / "history.db") as history:
        if recorded_in == "queue":
            original = app_module.TranscriptionTask(str(media))
            original.status = "finished"
            original.audio_track = track
            original.output_paths = [viewer.json_path]
            app.queue.append(original)
        if recorded_in in ("history", "history aliases"):
            app.history = history
            for path, ordinal in ((str(source_json), track), (str(tmp_path / "new.json"), 0)):
                source = history.insert_transcription(str(media), run_options={"audio_track": ordinal})
                history.finish_transcription(source, "finished", output_paths=[path])
        transcript_viewer.TranscriptViewer._transcribe_again(viewer)

    assert selected == [track, track]
    assert transcribe_command(app.queue[-1])["audio_track"] == track


def test_preference_persists_without_deleting_either_file(tmp_path):
    source = str(tmp_path / "original.json")
    result = str(tmp_path / "original (1).json")
    db = tmp_path / "history.db"
    for name in ("original.json", "original (1).json"):
        (tmp_path / name).write_text(name, encoding="utf-8")
    with HistoryDB(db) as history:
        history.record_transcript_comparison(source, result)
        history.prefer_transcript(source, result, result)
        history.record_transcript_comparison(source, result)
    with HistoryDB(db) as history:
        assert history.transcript_comparison_for(source) == (source, result, result)
        assert history.transcript_comparison_for(result) == (source, result, result)
        history.prefer_transcript(source, result, None)
        assert history.transcript_comparison_for(source) == (source, result, None)
    assert (tmp_path / "original.json").read_text(encoding="utf-8") == "original.json"
    assert (tmp_path / "original (1).json").read_text(encoding="utf-8") == "original (1).json"


def test_output_relocation_moves_comparison_and_its_preference(tmp_path):
    source, result = (str(tmp_path / name) for name in ("original.json", "new.json"))
    moved_source, moved_result = (str(tmp_path / "archive" / name) for name in ("old.json", "new.json"))
    with HistoryDB(tmp_path / "history.db") as history:
        row_id = history.insert_transcription("example.wav")
        history.finish_transcription(row_id, "finished", output_paths=[result])
        history.record_transcript_comparison(source, result)
        history.prefer_transcript(source, result, result)
        assert history.relocate_transcription_outputs({source: moved_source, result: moved_result}) == 1
        assert history.transcript_comparison_for(moved_result) == (moved_source, moved_result, moved_result)
        assert history.transcript_comparison_for(source) is None


@pytest.mark.parametrize(("status", "history_saved", "expected"), [
    ("running", True, ["history", "comparison", "result"]),
    ("running", False, ["history", "result"]),
    ("error", True, ["history"]),
])
def test_comparison_only_opens_after_success_and_persistence(
    tmp_path, monkeypatch, status, history_saved, expected,
):
    source = tmp_path / "audio.json"
    source.write_bytes(b"original transcript")
    order = []
    app = SimpleNamespace(
        app_config={}, update_overall_progress=lambda: None, log=lambda _text: None,
        history=SimpleNamespace(finish_transcription=lambda *a, **k: order.append("history") or history_saved),
        complete_transcript_comparison=lambda _task: order.append("comparison"),
        show_last_result=lambda _task: order.append("result"),
    )
    service = TranscriptionService(app)
    monkeypatch.setattr(service, "_post_usage_stats", lambda *a, **k: None)
    task = SimpleNamespace(
        status=status, cancelled=False, start_time=time.time(), end_time=None,
        file_path=str(tmp_path / "audio.wav"), history_id=7, source_download=None,
        detected_language="", comparison_source=str(source), output_paths=["audio (1).json"],
    )
    service.finish_task({"task": task, "temporary": False}, keep_status=status == "error")
    assert order == expected
    assert source.read_bytes() == b"original transcript"
