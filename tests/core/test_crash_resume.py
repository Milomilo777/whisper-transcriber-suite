"""Tests for crash auto-resume.

``History.mark_interrupted`` flips rows from running → interrupted on
launch. The App's ``_maybe_offer_crash_resume`` reads them and, after
prompting the user, re-enqueues files that still exist on disk.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.history import HistoryDB


def test_mark_interrupted_flips_running_rows(tmp_path: Path) -> None:
    """A run-leftover row in 'running' must be flipped to
    'interrupted' on next launch's mark_interrupted call."""
    db = HistoryDB(tmp_path / "history.db")
    try:
        rid = db.insert_transcription(str(tmp_path / "a.wav"), language="en")
        # Sanity: row is currently 'running'.
        rows = db.list_transcriptions()
        assert any(r["id"] == rid and r["status"] == "running" for r in rows)
        # Simulate a relaunch.
        flipped = db.mark_interrupted()
        assert flipped >= 1
        rows = db.list_transcriptions()
        assert any(r["id"] == rid and r["status"] == "interrupted" for r in rows)
    finally:
        db.close()


def test_resume_dedupes_repeated_file_paths(tmp_path: Path) -> None:
    """When the same file was transcribed multiple times and all
    rows are interrupted, the App-side resume logic must dedup by
    file_path so we don't enqueue it three times.

    We replicate the App-side dedup in pure Python (the actual code
    lives inside App.__init__ which requires Tk) and exercise it
    against the DB.
    """
    db = HistoryDB(tmp_path / "history.db")
    try:
        media = tmp_path / "show.wav"
        media.write_bytes(b"x")
        a = db.insert_transcription(str(media), language="en")
        b = db.insert_transcription(str(media), language="en")
        c = db.insert_transcription(str(media), language="en")
        assert len({a, b, c}) == 3  # three distinct history rows
        db.mark_interrupted()

        rows = db.list_transcriptions(limit=200)
        interrupted = [
            r for r in rows
            if r.get("status") == "interrupted"
            and r.get("file_path")
            and os.path.isfile(r["file_path"])
        ]
        seen: set[str] = set()
        unique = []
        for r in interrupted:
            if r["file_path"] not in seen:
                seen.add(r["file_path"])
                unique.append(r)
        assert len(unique) == 1
        assert unique[0]["file_path"] == str(media)
    finally:
        db.close()


def test_resume_drops_rows_for_missing_files(tmp_path: Path) -> None:
    """If the source file no longer exists on disk, the row must
    NOT be re-enqueued (the App-side filter excludes it)."""
    db = HistoryDB(tmp_path / "history.db")
    try:
        db.insert_transcription(str(tmp_path / "ghost.wav"), language="en")
        db.mark_interrupted()
        rows = db.list_transcriptions()
        # Filter mirrors App._maybe_offer_crash_resume's predicate.
        eligible = [
            r for r in rows
            if r.get("status") == "interrupted"
            and r.get("file_path")
            and os.path.isfile(r["file_path"])
        ]
        assert eligible == []
    finally:
        db.close()
