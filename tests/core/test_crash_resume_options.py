"""Crash-resume keeps the run's own options: the time range and the mixed languages.

The history row of a transcription recorded only its file, model, language and
Whisper task, so a job re-queued after a crash ran on the whole file and in one
language, and its checkpoint (made for the clip) no longer matched.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from core.history import HistoryDB
from core.task import TranscriptionTask, apply_run_options, task_run_options


def _task(path: str = "a.wav") -> TranscriptionTask:
    t = TranscriptionTask(path)
    t.clip_start, t.clip_end = 12.5, 90.0
    t.languages = ("fa", "en")
    return t


def test_run_options_round_trip_through_the_history_row(tmp_path: Path) -> None:
    db = HistoryDB(tmp_path / "history.db")
    try:
        db.insert_transcription("a.wav", language="fa", run_options=task_run_options(_task()))
        db.mark_interrupted()
        row = db.list_transcriptions(limit=5)[0]
    finally:
        db.close()
    fresh = TranscriptionTask("a.wav")
    apply_run_options(fresh, row.get("run_options"))
    assert (fresh.clip_start, fresh.clip_end) == (12.5, 90.0)
    assert fresh.languages == ("fa", "en")


def test_a_plain_run_stores_nothing_and_restores_nothing(tmp_path: Path) -> None:
    assert task_run_options(TranscriptionTask("a.wav")) == {}
    db = HistoryDB(tmp_path / "history.db")
    try:
        db.insert_transcription("a.wav")
        row = db.list_transcriptions(limit=5)[0]
    finally:
        db.close()
    fresh = TranscriptionTask("a.wav")
    apply_run_options(fresh, row.get("run_options"))
    assert (fresh.clip_start, fresh.clip_end, fresh.languages) == (None, None, None)


def test_an_open_ended_range_keeps_its_one_bound() -> None:
    t = TranscriptionTask("a.wav")
    t.clip_start = 30.0
    fresh = TranscriptionTask("a.wav")
    apply_run_options(fresh, task_run_options(t))
    assert (fresh.clip_start, fresh.clip_end) == (30.0, None)


def test_damaged_or_foreign_options_are_ignored() -> None:
    for bad in (None, "", "not json", [1, 2], {"clip_start": "x", "languages": ["fa"]},
                {"clip_start": -5, "clip_end": float("nan")}, {"languages": [1, 2]}):
        fresh = TranscriptionTask("a.wav")
        apply_run_options(fresh, bad)
        assert (fresh.clip_start, fresh.clip_end, fresh.languages) == (None, None, None), bad


def test_an_older_history_db_gains_the_column(tmp_path: Path) -> None:
    path = tmp_path / "history.db"
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE transcriptions (id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL,"
        " model TEXT, status TEXT NOT NULL, started_at INTEGER, finished_at INTEGER,"
        " duration_seconds REAL, language TEXT, output_paths TEXT, error TEXT)")
    conn.execute("INSERT INTO transcriptions (file_path, status) VALUES ('old.wav', 'interrupted')")
    conn.commit()
    conn.close()
    db = HistoryDB(path)
    try:
        rows = db.list_transcriptions(limit=5)
        assert rows[0]["file_path"] == "old.wav"
        fresh = TranscriptionTask("old.wav")
        apply_run_options(fresh, rows[0].get("run_options"))
        assert fresh.clip_start is None and fresh.languages is None
        db.insert_transcription("b.wav", run_options=task_run_options(_task("b.wav")))
        assert db.list_transcriptions(limit=1)[0]["run_options"]["languages"] == ["fa", "en"]
    finally:
        db.close()


def test_an_inverted_range_keeps_its_start_only() -> None:
    for end in (30.0, 60.0):
        fresh = TranscriptionTask("a.wav")
        apply_run_options(fresh, {"clip_start": 60.0, "clip_end": end})
        assert (fresh.clip_start, fresh.clip_end) == (60.0, None), end
