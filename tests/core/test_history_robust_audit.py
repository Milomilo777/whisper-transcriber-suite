"""History DB robustness: corrupt-file recovery keeps every archived copy,
and databases written by older schemas open and migrate."""
import logging
import sqlite3

import core.history as history_mod
from core.history import HistoryDB


def _corrupt_file(path, payload: bytes = b"0" * 1024) -> None:
    with open(path, "wb") as fh:
        fh.write(payload)


def _archives(tmp_path):
    return sorted(p for p in tmp_path.glob("history.db.corrupt*")
                  if not p.name.endswith(("-wal", "-shm")))


def test_corrupt_db_recovered_to_timestamped_archive(tmp_path, caplog):
    """A zeroed header is detected, moved aside under a timestamped name and
    a fresh database is created; the recovery is logged with the archive
    path so the user can find the old file."""
    db_path = tmp_path / "history.db"
    _corrupt_file(db_path)

    with caplog.at_level(logging.WARNING, logger=history_mod.logger.name):
        db = HistoryDB(db_path)
    try:
        assert db.insert_download("https://x") > 0
    finally:
        db.close()

    archives = _archives(tmp_path)
    assert len(archives) == 1
    assert archives[0].name.startswith("history.db.corrupt.")
    assert archives[0].read_bytes() == b"0" * 1024
    assert any(str(archives[0]) in r.getMessage() for r in caplog.records)


def test_second_corruption_keeps_first_archive(tmp_path):
    """A later corruption must never delete the copy archived by an earlier
    one: both archives exist with their original bytes."""
    db_path = tmp_path / "history.db"
    _corrupt_file(db_path, b"first-corrupt" * 64)
    HistoryDB(db_path).close()
    _corrupt_file(db_path, b"second-corrupt" * 64)
    HistoryDB(db_path).close()

    contents = sorted(p.read_bytes() for p in _archives(tmp_path))
    assert contents == sorted([b"first-corrupt" * 64, b"second-corrupt" * 64])


def test_two_recoveries_in_same_second_keep_two_archives(tmp_path, monkeypatch):
    """The timestamp has one-second resolution; two recoveries inside the
    same second must still produce two distinct archives (os.replace would
    otherwise overwrite the first)."""
    monkeypatch.setattr(history_mod, "_archive_stamp", lambda: "20261012-112100")
    db_path = tmp_path / "history.db"
    _corrupt_file(db_path, b"one" * 300)
    HistoryDB(db_path).close()
    _corrupt_file(db_path, b"two" * 300)
    HistoryDB(db_path).close()
    _corrupt_file(db_path, b"three" * 300)
    HistoryDB(db_path).close()

    archives = _archives(tmp_path)
    assert len(archives) == 3
    assert sorted(p.read_bytes() for p in archives) == sorted(
        [b"one" * 300, b"two" * 300, b"three" * 300])


def test_archive_name_skips_a_taken_sidecar_name(tmp_path, monkeypatch):
    """An earlier archive's -wal sidecar may outlive its main file; the new
    archive must not take a name whose sidecar would overwrite it."""
    stamp = "20261012-112100"
    monkeypatch.setattr(history_mod, "_archive_stamp", lambda: stamp)
    old_wal = tmp_path / f"history.db.corrupt.{stamp}-wal"
    old_wal.write_bytes(b"old-wal")
    db_path = tmp_path / "history.db"
    _corrupt_file(db_path)
    (tmp_path / "history.db-wal").write_bytes(b"new-wal")
    HistoryDB(db_path).close()

    assert old_wal.read_bytes() == b"old-wal"
    assert not (tmp_path / f"history.db.corrupt.{stamp}").exists()
    assert (tmp_path / f"history.db.corrupt.{stamp}-2").read_bytes() == b"0" * 1024


def test_healthy_db_is_not_archived(tmp_path):
    db_path = tmp_path / "history.db"
    db = HistoryDB(db_path)
    db.insert_download("https://keep")
    db.close()
    db = HistoryDB(db_path)
    try:
        assert db.list_downloads()[0]["url"] == "https://keep"
    finally:
        db.close()
    assert _archives(tmp_path) == []


def test_schema_migrations_from_old_schema(tmp_path):
    """A database written by an older schema (no word_count/task/speed_x/
    device columns) opens, keeps its rows and gains the new columns."""
    db_path = tmp_path / "history.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT NOT NULL,
            title TEXT,
            folder TEXT,
            format_label TEXT,
            status TEXT NOT NULL,
            started_at INTEGER,
            finished_at INTEGER,
            output_paths TEXT,
            detected_language TEXT,
            error TEXT
        );
        CREATE TABLE IF NOT EXISTS transcriptions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            model TEXT,
            status TEXT NOT NULL,
            started_at INTEGER,
            finished_at INTEGER,
            duration_seconds REAL,
            language TEXT,
            output_paths TEXT,
            error TEXT
        );
        INSERT INTO transcriptions (file_path, model, status, started_at)
            VALUES ('/old/a.wav', 'base', 'done', 1);
    """)
    conn.commit()
    conn.close()

    db = HistoryDB(db_path)
    try:
        cols = {row[1] for row in
                db._conn.execute("PRAGMA table_info(transcriptions)").fetchall()}
        assert {"word_count", "task", "speed_x", "device"} <= cols
        assert db.list_transcriptions()[0]["file_path"] == "/old/a.wav"
    finally:
        db.close()
    assert _archives(tmp_path) == []
