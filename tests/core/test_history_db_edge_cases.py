"""Edge cases for ``core.history.HistoryDB``.

Persian/RTL and emoji text and Windows-style paths must come back from the
database exactly as stored, large numbers must not overflow, and the
Statistics totals must survive a finished row whose duration is NULL.
Hermetic: a throw-away database under ``tmp_path``.
"""
from __future__ import annotations

import pytest

from core.history import HistoryDB


@pytest.fixture
def db(tmp_path):
    database = HistoryDB(tmp_path / "history.db")
    yield database
    database.close()


def test_persian_rtl_and_emoji_text_round_trips(db):
    persian = "\u0633\u0644\u0627\u0645 \u062f\u0646\u06cc\u0627 \u200c \u202b\u0645\u062a\u0646\u202c"
    mixed = "\u3053\u3093\u306b\u3061\u306f \U0001f31f \u05d0\u05d1\u05d2"
    rid = db.insert_transcription(mixed, language=persian, model=mixed)
    db.finish_transcription(rid, "finished", error=mixed, language=persian)

    rows = db.list_transcriptions()
    assert len(rows) == 1
    assert rows[0]["file_path"] == mixed
    assert rows[0]["language"] == persian
    assert rows[0]["model"] == mixed
    assert rows[0]["error"] == mixed


def test_windows_style_paths_round_trip(db):
    source = "C:\\Users\\User\\Music\\test.wav"
    outputs = ["D:\\Downloads\\output.srt", "\\\\server\\share\\output.txt"]
    rid = db.insert_transcription(source)
    db.finish_transcription(rid, "finished", output_paths=outputs)

    row = db.list_transcriptions()[0]
    assert row["file_path"] == source
    assert row["output_paths"] == outputs


def test_download_output_paths_round_trip_with_non_ascii_names(db):
    outputs = ["/tmp/\u0641\u0627\u06cc\u0644 \u06f1.mp4", "/tmp/caf\u00e9.mp3"]
    rid = db.insert_download("https://example.invalid/v")
    db.finish_download(rid, "finished", output_paths=outputs)

    assert db.list_downloads()[0]["output_paths"] == outputs


def test_long_duration_and_large_word_count_are_stored_exactly(db):
    rid = db.insert_transcription("test.wav")
    db.finish_transcription(
        rid, "finished", duration_seconds=1e10, word_count=1_000_000_000_000
    )

    row = db.list_transcriptions()[0]
    assert row["duration_seconds"] == 1e10
    assert row["word_count"] == 1_000_000_000_000


def test_stats_ignore_a_finished_row_with_a_null_duration(db):
    timed = db.insert_transcription("a.wav")
    db.finish_transcription(timed, "finished", duration_seconds=120.0)
    untimed = db.insert_transcription("b.wav")
    with db._txn() as conn:  # a row from an older version, or a hand edit
        conn.execute(
            "UPDATE transcriptions SET status='finished', duration_seconds=NULL"
            " WHERE id=?",
            (untimed,),
        )

    stats = db.stats()
    assert stats["transcriptions_finished"] == 2
    assert stats["transcription_minutes"] == 2.0
