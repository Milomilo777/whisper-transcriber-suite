"""A job that found no speech says so in the Queue instead of a plain "✓ finished".

Round-2 screenshot critics (verification pass 4, 2026-10-21): a 2-s horse sound showed
"✓ finished 100 %" and "English (not sure)" in the Queue, and the result card a tick, with only
an orange sentence saying the files are empty. The history row already drops the language
(transcription_service._history_entry). Windowless: a recording tree stands in for the Treeview.
"""
from __future__ import annotations

import os
import types

import app.app as appmod
from app.domain.tasks import TranscriptionTask
from app.widgets.tabs import status_label, task_status_label
from tests.app.test_bidi_display import _queue_app


def _finished(no_speech: bool) -> TranscriptionTask:
    task = TranscriptionTask(os.path.join("media", "horse.mp3"))
    task.status = "finished"
    task.progress = 100
    task.no_speech = no_speech
    task.detected_language = "en"
    task.language_probability = 0.4
    return task


def test_a_no_speech_job_has_its_own_status_words():
    assert task_status_label(_finished(True)) == "⚠ no speech found"
    assert task_status_label(_finished(False)) == status_label("finished")
    assert task_status_label(types.SimpleNamespace(status="running")) == status_label("running")


def test_the_queue_row_says_no_speech_and_shows_no_language():
    app = _queue_app([_finished(True), _finished(False)])
    appmod.App.refresh(app)  # type: ignore[arg-type]
    (silent, _t1), (spoken, _t2) = app.tree.rows
    assert silent[1] == "⚠ no speech found" and silent[4] == ""
    assert spoken[1] == status_label("finished") and spoken[4] != ""
