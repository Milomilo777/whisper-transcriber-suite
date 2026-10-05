"""Tests for P4-4 usage stats: word_count migration, the pure payload
builder, and the telemetry opt-in gate."""
from __future__ import annotations

import inspect
import sqlite3

import pytest

from core import stats
from core.history import HistoryDB


# --- word_count migration ---------------------------------------------------

def _columns(path) -> set[str]:
    conn = sqlite3.connect(str(path))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(transcriptions)").fetchall()}
    conn.close()
    return cols


def test_word_count_column_added(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    db.close()
    assert "word_count" in _columns(tmp_path / "h.db")


def test_word_count_migration_idempotent(tmp_path):
    # Open twice — the guarded ALTER must not raise "duplicate column".
    HistoryDB(tmp_path / "h.db").close()
    HistoryDB(tmp_path / "h.db").close()
    assert "word_count" in _columns(tmp_path / "h.db")


def test_word_count_migrates_legacy_table(tmp_path):
    # Simulate an OLD db that predates the column: create transcriptions
    # WITHOUT word_count, then let HistoryDB migrate it on open.
    path = tmp_path / "legacy.db"
    conn = sqlite3.connect(str(path))
    conn.execute(
        "CREATE TABLE transcriptions ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT, file_path TEXT NOT NULL,"
        " model TEXT, status TEXT NOT NULL, started_at INTEGER,"
        " finished_at INTEGER, duration_seconds REAL, language TEXT,"
        " output_paths TEXT, error TEXT)"
    )
    conn.execute(
        "INSERT INTO transcriptions (file_path, status) VALUES ('x.wav', 'finished')"
    )
    conn.commit()
    conn.close()

    db = HistoryDB(path)
    db.close()
    assert "word_count" in _columns(path)


def test_word_count_populated(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    rid = db.insert_transcription("/tmp/x.wav", model="large-v3", language="en")
    db.finish_transcription(rid, "finished", word_count=123)
    rows = db.list_transcriptions()
    db.close()
    assert rows[0]["word_count"] == 123


def test_word_count_defaults_zero(tmp_path):
    db = HistoryDB(tmp_path / "h.db")
    rid = db.insert_transcription("/tmp/x.wav")
    db.finish_transcription(rid, "finished")  # no word_count passed
    rows = db.list_transcriptions()
    db.close()
    assert rows[0]["word_count"] == 0


# --- pure helpers -----------------------------------------------------------

def test_count_words():
    assert stats.count_words("hello world foo") == 3
    assert stats.count_words("") == 0
    assert stats.count_words(None) == 0  # type: ignore[arg-type]


def test_count_words_in_segments():
    segs = [{"text": "one two"}, {"text": "three"}, {"text": ""}]
    assert stats.count_words_in_segments(segs) == 3
    assert stats.count_words_in_segments([]) == 0
    assert stats.count_words_in_segments(None) == 0


def test_count_words_in_segments_ignores_non_string_text():
    """A None / non-string / missing text counts as 0 words, not 1.

    Regression: str(None) -> "None" was previously counted as one word.
    """
    segs = [
        {"text": "one two"},
        {"text": None},        # was miscounted as 1 ("None")
        {},                    # missing key
        {"text": 123},         # non-string
        {"text": "three"},
    ]
    assert stats.count_words_in_segments(segs) == 3  # type: ignore[list-item]


def test_audio_duration_from_segments():
    segs = [{"start": 0.0, "end": 2.0}, {"start": 2.0, "end": 6.5}]
    assert stats.audio_duration_from_segments(segs) == pytest.approx(6.5)
    assert stats.audio_duration_from_segments([]) == 0.0


def test_build_stats_payload_pure():
    p = stats.build_stats_payload(
        model="large-v3",
        language="en",
        audio_duration=123.456,
        transcription_time=42.0,
        status="finished",
        word_count=99,
    )
    assert p["model"] == "large-v3"
    assert p["language"] == "en"
    assert p["audio_duration"] == "123.456"
    assert p["transcription_time"] == "42.000"
    assert p["status"] == "finished"
    assert p["word_count"] == "99"
    assert p["form_submitted"] == "1"


# --- no file name -----------------------------------------------------------

def test_payload_builder_takes_no_file_argument():
    params = inspect.signature(stats.build_stats_payload).parameters
    assert not [n for n in params if "file" in n.lower() or "path" in n.lower()]
    with pytest.raises(TypeError):
        stats.build_stats_payload(  # type: ignore[call-arg]
            file_name="a.mp4", model="m", language="en",
            audio_duration=1.0, transcription_time=1.0, status="finished",
        )


def test_payload_has_no_file_name_key():
    p = stats.build_stats_payload(
        model="m", language="en", audio_duration=1.0,
        transcription_time=1.0, status="finished",
    )
    assert "file_name" not in p
    assert not [k for k in p if "file" in k.lower() or "path" in k.lower()]


# --- opt-in gate ------------------------------------------------------------

def _payload():
    return stats.build_stats_payload(
        model="m", language="en",
        audio_duration=1.0, transcription_time=1.0, status="finished",
    )


def test_no_post_when_telemetry_off(monkeypatch):
    started = {"n": 0}
    monkeypatch.setattr(stats, "_post", lambda *a, **k: started.__setitem__("n", started["n"] + 1))
    cfg = {"telemetry_opt_in": False, "stats_url": "https://example.com/s.php"}
    assert stats.post_stats_async(cfg, _payload()) is False


def test_no_post_when_no_url(monkeypatch):
    monkeypatch.setattr(stats, "_post", lambda *a, **k: None)
    cfg = {"telemetry_opt_in": True, "stats_url": ""}
    assert stats.post_stats_async(cfg, _payload()) is False


def test_posts_when_opted_in(monkeypatch):
    calls = {}

    def fake_post(url, payload, timeout):
        calls["url"] = url
        calls["payload"] = payload

    monkeypatch.setattr(stats, "_post", fake_post)
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.com/s.php"}
    started = stats.post_stats_async(cfg, _payload(), timeout=1.0)
    assert started is True
    # The POST runs on a daemon thread — give it a moment to land.
    import time as _t
    for _ in range(50):
        if "url" in calls:
            break
        _t.sleep(0.01)
    assert calls.get("url") == "https://example.com/s.php"
    assert calls["payload"] == _payload()


def test_no_post_with_empty_payload(monkeypatch):
    monkeypatch.setattr(stats, "_post", lambda *a, **k: None)
    cfg = {"telemetry_opt_in": True, "stats_url": "https://example.com/s.php"}
    assert stats.post_stats_async(cfg, {}) is False


# --- worker-side transcript stats (transcriber -> "done" event) -------------

def test_record_transcript_stats_sets_task_fields():
    from core.task import TranscriptionTask
    from core.transcriber import _record_transcript_stats

    task = TranscriptionTask("a.mp4")
    segments = [
        {"start": 0.0, "end": 2.0, "text": "one two"},
        {"start": 2.0, "end": 5.5, "text": "three four five"},
    ]
    _record_transcript_stats(task, segments)
    assert task.word_count == 5
    assert task.audio_duration == 5.5


def test_record_transcript_stats_empty_segments_leave_zeroes():
    from core.task import TranscriptionTask
    from core.transcriber import _record_transcript_stats

    task = TranscriptionTask("a.mp4")
    _record_transcript_stats(task, [])
    assert task.word_count == 0
    assert task.audio_duration == 0.0
