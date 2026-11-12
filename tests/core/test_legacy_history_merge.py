"""Retries are transactional, idempotent and preserve new history metadata."""
import errno
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from core import config as cfg
from core.history import HistoryDB, import_legacy_history
from tests.core.test_legacy_app_migration import dirs


def make_database(path, label):
    with HistoryDB(path) as database:
        download = database.insert_download("https://example.invalid/" + label, title=label)
        database.finish_download(download, "finished", output_paths=[label + ".mp4"],
                                 detected_language="fr")
        task = database.insert_transcription(label + ".wav", model="tiny", language="fr",
                                             task="translate", run_options={"start_time": 1.25})
        database.finish_transcription(task, "finished", output_paths=[label + ".srt"],
                                      duration_seconds=7.5, language="fr", model="tiny")


def records(path, table):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [{key: row[key] for key in row.keys() if key != "id"}
                for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY id')]


def test_merge_keeps_all_metadata_and_conflicting_new_ids(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    make_database(old, "legacy")
    make_database(new, "current")
    expected = {table: records(new, table) + records(old, table)
                for table in ("downloads", "transcriptions")}
    original = old.read_bytes()
    import_legacy_history(old, new, "legacy-source")
    import_legacy_history(old, new, "legacy-source")
    assert all(records(new, table) == rows for table, rows in expected.items())
    assert old.read_bytes() == original


def test_failure_rolls_back_both_tables_and_retry_receipt(tmp_path):
    old, new = tmp_path / "old.db", tmp_path / "new.db"
    make_database(old, "legacy")
    make_database(new, "current")
    before = {table: records(new, table) for table in ("downloads", "transcriptions")}
    with sqlite3.connect(new) as connection:
        connection.execute("CREATE TRIGGER fail_import BEFORE INSERT ON transcriptions "
                           "WHEN NEW.file_path='legacy.wav' BEGIN SELECT RAISE(ABORT, 'synthetic import failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="synthetic import failure"):
        import_legacy_history(old, new, "legacy-source")
    assert all(records(new, table) == rows for table, rows in before.items())
    with sqlite3.connect(new) as connection:
        connection.execute("DROP TRIGGER fail_import")
    import_legacy_history(old, new, "legacy-source")
    assert len(records(new, "downloads")) == len(records(new, "transcriptions")) == 2


def test_deleted_imported_row_is_not_resurrected_by_receipt_write_retry(dirs, monkeypatch):
    new, old = dirs
    source = old["data"] / "history.db"
    destination = new["data"] / "history.db"
    make_database(source, "legacy")
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    write = cfg._write_disk_dict
    failed = []

    def fail_completion(path, data):
        if Path(path).name == "legacy-history-migration.json" and data.get("complete"):
            failed.append(True)
            raise OSError(errno.ENOSPC, "synthetic receipt write failure")
        write(path, data)

    with monkeypatch.context() as failure:
        failure.setattr(cfg, "_write_disk_dict", fail_completion)
        cfg.migrate_legacy_app_data()
    assert failed and len(records(destination, "transcriptions")) == 1
    with sqlite3.connect(destination) as connection:
        connection.execute("DELETE FROM transcriptions")
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert records(destination, "transcriptions") == []
    assert len(records(destination, "downloads")) == 1
    assert json.loads((new["config"] / "legacy-history-migration.json").read_text())["complete"] is True


def test_receipt_creation_failure_does_not_strand_history_behind_new_config(dirs, monkeypatch):
    new, old = dirs
    make_database(old["data"] / "history.db", "legacy")
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    write = cfg._write_disk_dict

    def fail_receipt(path, data):
        if Path(path).name == "legacy-history-migration.json":
            raise OSError(errno.ENOSPC, "synthetic intent write failure")
        write(path, data)

    with monkeypatch.context() as failure:
        failure.setattr(cfg, "_write_disk_dict", fail_receipt)
        cfg.migrate_legacy_app_data()
    assert not (new["config"] / "config.json").exists()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert len(records(new["data"] / "history.db", "transcriptions")) == 1


def test_completed_import_does_not_recreate_deliberately_removed_history(dirs):
    new, old = dirs
    make_database(old["data"] / "history.db", "legacy")
    (old["config"] / "config.json").write_text('{}', encoding="utf-8")
    cfg.migrate_legacy_app_data()
    destination = new["data"] / "history.db"
    destination.unlink()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert not destination.exists()


@pytest.mark.parametrize("contents", ["not json", '{"version":1,"source":"foreign","complete":false}'])
def test_invalid_or_foreign_receipt_never_imports_over_existing_profile(dirs, contents):
    new, old = dirs
    make_database(old["data"] / "history.db", "legacy")
    (old["config"] / "config.json").write_text('{}', encoding="utf-8")
    (new["config"] / "config.json").write_text('{"theme":"light"}', encoding="utf-8")
    marker = new["config"] / "legacy-history-migration.json"
    marker.write_text(contents, encoding="utf-8")
    cfg.migrate_legacy_app_data()
    assert marker.read_text(encoding="utf-8") == contents
    assert not (new["data"] / "history.db").exists()
    assert json.loads((new["config"] / "config.json").read_text())["theme"] == "light"


def test_source_and_destination_alias_never_imports_into_original(tmp_path):
    source = tmp_path / "source.db"
    make_database(source, "legacy")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="same"):
        import_legacy_history(source, source, "legacy-source")
    assert source.read_bytes() == original


def test_two_processes_import_only_one_copy_of_each_job(tmp_path):
    source, destination = tmp_path / "old.db", tmp_path / "new.db"
    make_database(source, "legacy")
    make_database(destination, "current")
    script = """
from pathlib import Path
import sys, time
from core import offline
offline._override = True
from core.history import import_legacy_history
source, destination, ready, go = map(Path, sys.argv[1:])
ready.touch()
deadline = time.monotonic() + 10
while not go.exists():
    if time.monotonic() > deadline:
        raise TimeoutError('parent did not release imports')
    time.sleep(.01)
import_legacy_history(source, destination, 'legacy-source')
"""
    ready = [tmp_path / "ready-1", tmp_path / "ready-2"]
    go = tmp_path / "start"
    import os
    import time
    processes = [subprocess.Popen(
        [sys.executable, "-c", script, str(source), str(destination), str(marker), str(go)],
        cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        env={**os.environ, "WTS_PROFILE_DIR": str(tmp_path / ("profile-" + marker.name))},
    ) for marker in ready]
    try:
        deadline = time.monotonic() + 15
        while not all(marker.exists() for marker in ready):
            assert all(process.poll() is None for process in processes)
            assert time.monotonic() < deadline
            time.sleep(.01)
        go.touch()
        for process in processes:
            stdout, stderr = process.communicate(timeout=20)
            assert process.returncode == 0, (stdout, stderr)
        assert len(records(destination, "downloads")) == 2
        assert len(records(destination, "transcriptions")) == 2
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
                process.communicate(timeout=5)


def test_unknown_source_metadata_refuses_to_silently_drop_fields(tmp_path):
    source, destination = tmp_path / "old.db", tmp_path / "new.db"
    make_database(source, "legacy")
    make_database(destination, "current")
    with sqlite3.connect(source) as connection:
        connection.execute("ALTER TABLE transcriptions ADD COLUMN future_metadata TEXT")
        connection.execute("UPDATE transcriptions SET future_metadata='irreplaceable metadata'")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="Unsupported legacy"):
        import_legacy_history(source, destination, "legacy-source")
    assert len(records(destination, "downloads")) == len(records(destination, "transcriptions")) == 1
    assert source.read_bytes() == original


def test_settings_saved_after_intent_failure_still_allow_history_retry(dirs, monkeypatch):
    new, old = dirs
    make_database(old["data"] / "history.db", "legacy")
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    write = cfg._write_disk_dict

    def fail_receipt(path, data):
        if Path(path).name == "legacy-history-migration.json":
            raise OSError(errno.ENOSPC, "synthetic intent write failure")
        write(path, data)

    with monkeypatch.context() as failure:
        failure.setattr(cfg, "_write_disk_dict", fail_receipt)
        settings = cfg.load_config(fetch_online=False)
    assert not (new["config"] / "config.json").exists()
    settings["theme"] = "light"
    cfg.save_config(settings)
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert len(records(new["data"] / "history.db", "transcriptions")) == 1
    assert json.loads((new["config"] / "config.json").read_text())["theme"] == "light"


def test_colliding_source_id_does_not_consume_later_free_source_id(tmp_path):
    source, destination = tmp_path / "old.db", tmp_path / "new.db"
    make_database(source, "legacy")
    make_database(destination, "current")
    with HistoryDB(source) as database:
        assert database.insert_transcription("second-legacy.wav") == 2
    import_legacy_history(source, destination, "legacy-source")
    with sqlite3.connect(destination) as connection:
        by_id = dict(connection.execute("SELECT id, file_path FROM transcriptions"))
    assert by_id[1] == "current.wav"
    assert by_id[2] == "second-legacy.wav"
    assert set(by_id.values()) == {"current.wav", "legacy.wav", "second-legacy.wav"}


def test_largest_sqlite_id_still_allows_collision_remapping_into_a_free_gap(tmp_path):
    source, destination = tmp_path / "old.db", tmp_path / "new.db"
    make_database(source, "legacy")
    make_database(destination, "current")
    with sqlite3.connect(source) as connection:
        connection.execute("INSERT INTO transcriptions(id,file_path,status) VALUES(?,?,'finished')",
                           ((1 << 63) - 1, "largest-id.wav"))
    import_legacy_history(source, destination, "legacy-source")
    with sqlite3.connect(destination) as connection:
        by_id = dict(connection.execute("SELECT id,file_path FROM transcriptions"))
    assert by_id[1] == "current.wav"
    assert by_id[(1 << 63) - 1] == "largest-id.wav"
    assert by_id[2] == "legacy.wav"


def test_settings_save_is_refused_if_missing_intent_still_cannot_be_recorded(dirs, monkeypatch):
    new, old = dirs
    make_database(old["data"] / "history.db", "legacy")
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    replace = cfg._replace_with_retry

    def fail_intent(staged, target):
        if Path(target).name == "legacy-history-migration.json":
            raise OSError(errno.ENOSPC, "synthetic intent publication failure")
        replace(staged, target)

    monkeypatch.setattr(cfg, "_replace_with_retry", fail_intent)
    settings = cfg.load_config(fetch_online=False)
    with pytest.raises(cfg.ConfigSaveError, match="intent publication failure"):
        cfg.save_config(settings)
    assert not (new["config"] / "config.json").exists()
    assert not (new["config"] / "legacy-history-migration.json").exists()
    assert len(records(old["data"] / "history.db", "transcriptions")) == 1


def test_noninteger_history_id_is_refused_without_partial_import(tmp_path):
    source, destination = tmp_path / "old.db", tmp_path / "new.db"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE downloads(id TEXT PRIMARY KEY, url TEXT, status TEXT)")
        connection.execute("INSERT INTO downloads VALUES('foreign-id','https://example.invalid','finished')")
    make_database(destination, "current")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="Unsupported legacy"):
        import_legacy_history(source, destination, "legacy-source")
    assert source.read_bytes() == original
    assert len(records(destination, "downloads")) == 1


@pytest.mark.parametrize("columns", [
    "id INTEGER, url TEXT, status TEXT, PRIMARY KEY(id,url)",
    "id INTEGER PRIMARY KEY DESC, url TEXT, status TEXT",
])
def test_integer_declaration_without_rowid_alias_cannot_crash_import(tmp_path, columns):
    source, destination = tmp_path / "old.db", tmp_path / "new.db"
    with sqlite3.connect(source) as connection:
        connection.execute(f"CREATE TABLE downloads({columns})")
        connection.execute("INSERT INTO downloads VALUES('foreign-id','https://example.invalid','finished')")
    make_database(destination, "current")
    original = source.read_bytes()
    with pytest.raises(ValueError, match="Unsupported legacy"):
        import_legacy_history(source, destination, "legacy-source")
    assert source.read_bytes() == original
    assert len(records(destination, "downloads")) == 1
