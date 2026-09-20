"""Tests for transcription_service.transcribe_command.

This is the JSON the parent dispatches to the worker subprocess. The
worker has its OWN task object, so any field dropped here silently never
reaches transcription — the exact class of bug that shipped before
(forced language ignored, clip transcribing the whole file). These tests
lock the command contract.
"""
from __future__ import annotations

import json
import types

from app.services.transcription_service import transcribe_command


def _task(**kw):
    base = dict(
        file_path="clip.mp4", language=None, resume=False,
        clip_start=None, clip_end=None, output_formats=None,
    )
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_command_carries_all_worker_fields():
    cmd = transcribe_command(
        _task(language="fa", resume=True, clip_start=30.0, clip_end=90.0)
    )
    assert cmd["action"] == "transcribe"
    assert cmd["file_path"] == "clip.mp4"
    assert cmd["language"] == "fa"
    assert cmd["resume"] is True
    assert cmd["clip_start"] == 30.0
    assert cmd["clip_end"] == 90.0


def test_command_carries_output_formats():
    # The docx-never-written bug: the worker's config snapshot is stale, so
    # the selected formats MUST ride the command.
    cmd = transcribe_command(_task(output_formats=["srt", "docx"]))
    assert cmd["output_formats"] == ["srt", "docx"]


def test_command_defaults_for_a_plain_task():
    cmd = transcribe_command(_task())
    assert cmd["language"] is None
    assert cmd["resume"] is False
    assert cmd["clip_start"] is None
    assert cmd["clip_end"] is None


def test_command_is_json_serializable():
    # It's written to the worker's stdin as JSON.
    json.dumps(transcribe_command(_task(language="en", clip_start=5.0)))


def test_command_has_exactly_the_expected_keys():
    # Locks the contract: a silently-dropped (or stray) field fails here, so
    # the worker side and this command can't drift apart unnoticed.
    cmd = transcribe_command(_task())
    assert set(cmd) == {
        "action", "file_path", "language", "resume", "clip_start", "clip_end",
        "output_formats", "task_id",
    }


def test_command_carries_a_stable_task_id_from_history():
    """The correlation id is the existing history row id when available, and
    is cached so the transcribe command and a later control command agree."""
    t = _task(history_id=12)
    first = transcribe_command(t)
    second = transcribe_command(t)
    assert first["task_id"] == "h12"
    assert second["task_id"] == "h12"


def test_command_task_id_falls_back_to_uuid_without_a_history_row():
    t = _task()  # no history_id attr at all
    cmd = transcribe_command(t)
    assert cmd["task_id"].startswith("u")
    # Same id on a rebuild (cached on the task), not a fresh uuid each call.
    assert transcribe_command(t)["task_id"] == cmd["task_id"]
