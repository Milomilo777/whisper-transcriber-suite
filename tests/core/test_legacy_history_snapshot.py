"""Migration reads a coherent SQLite snapshot rather than unrelated WAL files."""
from pathlib import Path
import sqlite3

from core import config as cfg
from core.history import HistoryDB
from tests.core.test_legacy_app_migration import dirs


def test_checkpoint_between_file_copies_does_not_lose_committed_rows(dirs, monkeypatch):
    new, old = dirs
    (old["config"] / "config.json").write_text('{}', encoding="utf-8")
    source = old["data"] / "history.db"
    with HistoryDB(source) as database:
        database.insert_transcription("checkpointed.wav")
    connection = sqlite3.connect(source)
    try:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("INSERT INTO transcriptions(id, file_path, status) VALUES(2, 'committed-in-wal.wav', 'finished')")
        connection.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        copy = cfg.shutil.copy2

        def checkpoint_after_main_copy(src, dst, *args, **kwargs):
            result = copy(src, dst, *args, **kwargs)
            if Path(src) == source:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return result

        monkeypatch.setattr(cfg.shutil, "copy2", checkpoint_after_main_copy)
        cfg.migrate_legacy_app_data()
        with sqlite3.connect((new["data"] / "history.db").as_uri() + "?mode=ro", uri=True) as migrated:
            rows = migrated.execute("SELECT file_path FROM transcriptions ORDER BY id").fetchall()
        assert rows == [("checkpointed.wav",), ("committed-in-wal.wav",)]
        assert connection.execute("SELECT COUNT(*) FROM transcriptions").fetchone()[0] == 2
    finally:
        connection.close()
