"""Real SQLite history exposes transient legacy-copy failures across launches."""
import errno
import json
from pathlib import Path
import sqlite3

import pytest

from core import config as cfg
from core.history import HistoryDB
from core import history
from tests.core.test_legacy_app_migration import dirs


def make_legacy_history(old):
    source = old["data"] / "history.db"
    database = HistoryDB(source)
    try:
        row = database.insert_transcription("synthetic-legacy.wav", model="tiny", language="en")
        database.finish_transcription(row, "finished", output_paths=["synthetic-legacy.srt"],
                                      language="en", model="tiny")
    finally:
        database.close()
    return source


def history_rows(path):
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT file_path, status, output_paths, model, language FROM transcriptions"
        ).fetchall()
    for file_path, _status, outputs, model, language in rows:
        assert json.loads(outputs) == [str(Path(file_path).with_suffix(".srt"))]
        assert model == "tiny" and language == "en"
    return [(file_path, status) for file_path, status, *_ in rows]


@pytest.mark.parametrize("partial", [False, True])
def test_retry_after_history_copy_failure_recovers_legacy_rows(dirs, monkeypatch, partial):
    new, old = dirs
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    source = make_legacy_history(old)
    original = source.read_bytes()
    attempts = []

    def fail_history(src, dst, source_key):
        attempts.append(src)
        if Path(src) == source:
            if partial:
                Path(dst).parent.mkdir(parents=True, exist_ok=True)
                Path(dst).write_bytes(b"synthetic interrupted SQLite copy")
            raise OSError(errno.ENOSPC, "synthetic history copy failure")
        raise AssertionError("unexpected source")

    with monkeypatch.context() as failure:
        failure.setattr(history, "import_legacy_history", fail_history)
        cfg.migrate_legacy_app_data()
    assert attempts == [source], "the transient import failure must actually occur"
    destination = new["data"] / "history.db"
    if partial:
        assert destination.read_bytes() == b"synthetic interrupted SQLite copy"
    else:
        assert not destination.exists()
    assert json.loads((new["config"] / "config.json").read_text(encoding="utf-8"))["theme"] == "dark"
    assert source.read_bytes() == original
    cfg._legacy_migration_done = False  # a fresh app launch after storage recovers
    cfg.migrate_legacy_app_data()
    assert destination.is_file()
    assert history_rows(destination) == [("synthetic-legacy.wav", "finished")]
    assert source.read_bytes() == original
    if partial:
        archives = list(destination.parent.glob("history.db.corrupt.*"))
        assert any(path.read_bytes() == b"synthetic interrupted SQLite copy" for path in archives)


def test_existing_profile_does_not_resurrect_old_history(dirs):
    new, old = dirs
    (new["config"] / "config.json").write_text('{"theme":"light"}', encoding="utf-8")
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    source = make_legacy_history(old)
    cfg.migrate_legacy_app_data()
    assert not (new["data"] / "history.db").exists()
    assert json.loads((new["config"] / "config.json").read_text(encoding="utf-8"))["theme"] == "light"
    assert history_rows(source) == [("synthetic-legacy.wav", "finished")]


def test_missing_config_migration_merges_wal_history_without_replacing_new_rows(dirs):
    """Application import safely handles a reinstall's missing settings file.

    Keep the source open so its newest committed row remains in WAL; a raw
    main-file copy cannot preserve this state and the destination's newer row.
    """
    new, old = dirs
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    destination = new["data"] / "history.db"
    source = old["data"] / "history.db"
    with HistoryDB(destination) as current:
        current.insert_transcription("newer.wav")
    with HistoryDB(source) as legacy:
        with sqlite3.connect(source) as connection:
            assert connection.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone() == (0, 0, 0)
        legacy.insert_transcription("committed-in-wal.wav")
        wal = Path(str(source) + "-wal")
        assert wal.is_file() and wal.stat().st_size > 0
        raw_copy = old["data"] / "main-file-only.db"
        raw_copy.write_bytes(source.read_bytes())
        with sqlite3.connect(raw_copy) as connection:
            assert connection.execute("SELECT file_path FROM transcriptions").fetchall() == []
        cfg.migrate_legacy_app_data()
        with sqlite3.connect(destination) as connection:
            assert set(connection.execute("SELECT file_path FROM transcriptions")) == {
                ("newer.wav",), ("committed-in-wal.wav",),
            }
        with sqlite3.connect(source) as connection:
            assert connection.execute("SELECT file_path FROM transcriptions").fetchall() == [
                ("committed-in-wal.wav",)]
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    with sqlite3.connect(destination) as connection:
        assert connection.execute("SELECT COUNT(*) FROM transcriptions").fetchone() == (2,)


def test_successful_migration_copies_real_history_without_changing_source(dirs):
    new, old = dirs
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    source = make_legacy_history(old)
    original = source.read_bytes()
    cfg.migrate_legacy_app_data()
    assert history_rows(new["data"] / "history.db") == [("synthetic-legacy.wav", "finished")]
    assert source.read_bytes() == original


def test_retry_recovers_old_rows_without_replacing_new_history(dirs, monkeypatch):
    new, old = dirs
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    source = make_legacy_history(old)
    original = source.read_bytes()
    attempts = []

    def fail_history(src, dst, source_key):
        attempts.append(src)
        if Path(src) == source:
            raise OSError(errno.ENOSPC, "synthetic history copy failure")
        raise AssertionError("unexpected source")

    with monkeypatch.context() as failure:
        failure.setattr(history, "import_legacy_history", fail_history)
        cfg.migrate_legacy_app_data()
    assert attempts == [source], "the transient import failure must actually occur"
    database = HistoryDB(new["data"] / "history.db")
    try:
        row = database.insert_transcription("synthetic-new.wav", model="tiny", language="en")
        database.finish_transcription(row, "finished", output_paths=["synthetic-new.srt"],
                                      language="en", model="tiny")
    finally:
        database.close()
    (new["config"] / "config.json").write_text('{"theme":"light"}', encoding="utf-8")
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert source.read_bytes() == original
    assert json.loads((new["config"] / "config.json").read_text(encoding="utf-8"))["theme"] == "light"
    assert set(history_rows(new["data"] / "history.db")) == {
        ("synthetic-legacy.wav", "finished"), ("synthetic-new.wav", "finished"),
    }
