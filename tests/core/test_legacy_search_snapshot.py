"""A profile upgrade preserves the live search index as one SQLite snapshot."""
from contextlib import closing
import errno
import json
from pathlib import Path
import sqlite3

import pytest

from core import config as cfg
from core import search
from tests.core.test_legacy_app_migration import dirs


def legacy_index(old):
    (old["config"] / "config.json").write_text('{"theme":"dark"}', encoding="utf-8")
    source = old["data"] / "search.db"
    with closing(search._open_db(source)) as connection:
        connection.execute("INSERT INTO indexed_files VALUES ('checkpointed.json', 1, 2)")
        connection.commit()
    return source


def rows(path):
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as connection:
        assert connection.execute("PRAGMA quick_check").fetchall() == [("ok",)]
        return connection.execute("SELECT json_path FROM indexed_files ORDER BY json_path").fetchall()


def test_wal_checkpoint_during_migration_keeps_committed_search_rows(dirs, monkeypatch):
    new, old = dirs
    source = legacy_index(old)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO indexed_files VALUES ('wal-only.json', 3, 4)")
        writer.commit()
        assert Path(str(source) + "-wal").stat().st_size > 0
        copy = cfg.shutil.copy2

        def checkpoint_after_copy(src, dst, *args, **kwargs):
            result = copy(src, dst, *args, **kwargs)
            if Path(src) == source:
                writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            return result

        monkeypatch.setattr(cfg.shutil, "copy2", checkpoint_after_copy)
        cfg.migrate_legacy_app_data()
        assert rows(new["data"] / "search.db") == [("checkpointed.json",), ("wal-only.json",)]
        assert rows(source) == [("checkpointed.json",), ("wal-only.json",)]


@pytest.mark.parametrize("error_code", [errno.ENOSPC, errno.EIO])
def test_failed_search_sync_retries_after_config_was_created(dirs, monkeypatch, error_code):
    new, old = dirs
    source = legacy_index(old)
    original = source.read_bytes()
    attempts = []

    def fail_sync(fd):
        attempts.append(fd)
        raise OSError(error_code, "synthetic search storage failure")

    from core import _checkpoint
    with monkeypatch.context() as fault:
        # Limit the fault to the actual search snapshot, leaving config and
        # migration intent writes enabled so a retry must survive their creation.
        copy_index = search.copy_legacy_index
        def fail_index(src, dst):
            with monkeypatch.context() as native:
                native.setattr(_checkpoint.os, "fsync", fail_sync)
                return copy_index(src, dst)
        fault.setattr(search, "copy_legacy_index", fail_index)
        cfg.migrate_legacy_app_data()
    assert attempts, "the native sync failure must be exercised"
    assert not (new["data"] / "search.db").exists()
    assert not list(new["data"].glob(".search-migration-*"))
    assert json.loads((new["config"] / "config.json").read_text(encoding="utf-8"))["theme"] == "dark"
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert rows(new["data"] / "search.db") == [("checkpointed.json",)]
    assert source.read_bytes() == original


def test_existing_search_index_never_receives_legacy_sidecars(dirs):
    new, old = dirs
    source = legacy_index(old)
    with closing(sqlite3.connect(source)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO indexed_files VALUES ('legacy-wal.json', 3, 4)")
        writer.commit()
        destination = new["data"] / "search.db"
        with closing(search._open_db(destination)) as current:
            current.execute("INSERT INTO indexed_files VALUES ('current.json', 9, 10)")
            current.commit()
        expected = destination.read_bytes()
        cfg.migrate_legacy_app_data()
        assert destination.read_bytes() == expected
        assert not Path(str(destination) + "-wal").exists()
        assert not Path(str(destination) + "-shm").exists()
        assert rows(destination) == [("current.json",)]


def test_existing_profile_without_pending_intent_does_not_import_old_search(dirs):
    new, old = dirs
    legacy_index(old)
    (new["config"] / "config.json").write_text('{}', encoding="utf-8")
    cfg.migrate_legacy_app_data()
    assert not (new["data"] / "search.db").exists()


def test_completed_transfer_does_not_resurrect_deleted_search_index(dirs):
    new, old = dirs
    legacy_index(old)
    cfg.migrate_legacy_app_data()
    target = new["data"] / "search.db"
    assert rows(target) == [("checkpointed.json",)]
    target.unlink()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert not target.exists()


def test_failed_transfer_keeps_new_index_created_before_retry(dirs, monkeypatch):
    new, old = dirs
    legacy_index(old)
    with monkeypatch.context() as fault:
        def fail(*args):
            raise OSError(errno.ENOSPC, "synthetic snapshot failure")
        fault.setattr(search, "copy_legacy_index", fail)
        cfg.migrate_legacy_app_data()
    target = new["data"] / "search.db"
    with closing(search._open_db(target)) as connection:
        connection.execute("INSERT INTO indexed_files VALUES ('new-work.json', 1, 2)")
        connection.commit()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert rows(target) == [("new-work.json",)]


def test_publication_failure_leaves_no_partial_index_and_retries(dirs, monkeypatch):
    new, old = dirs
    source = legacy_index(old)
    original = source.read_bytes()
    publish = search.os.rename if search.os.name == "nt" else search.os.link
    attempts = []
    def fail_publish(src, dst, *args, **kwargs):
        if Path(dst) == new["data"] / "search.db":
            attempts.append(Path(src))
            assert rows(Path(src)) == [("checkpointed.json",)]
            raise PermissionError(errno.EACCES, "synthetic publication refusal")
        return publish(src, dst, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(search.os, "rename" if search.os.name == "nt" else "link", fail_publish)
        cfg.migrate_legacy_app_data()
    assert len(attempts) == 1
    assert not (new["data"] / "search.db").exists()
    assert not list(new["data"].glob(".search-migration-*"))
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert rows(new["data"] / "search.db") == [("checkpointed.json",)]
    assert source.read_bytes() == original


def test_concurrent_index_creator_wins_publication(dirs, monkeypatch):
    new, old = dirs
    source = legacy_index(old)
    destination = new["data"] / "search.db"
    publish = search.os.rename if search.os.name == "nt" else search.os.link
    attempts = []
    def create_before_publish(src, dst, *args, **kwargs):
        attempts.append(Path(dst))
        with closing(search._open_db(destination)) as connection:
            connection.execute("INSERT INTO indexed_files VALUES ('concurrent.json', 1, 2)")
            connection.commit()
        return publish(src, dst, *args, **kwargs)
    with monkeypatch.context() as fault:
        fault.setattr(search.os, "rename" if search.os.name == "nt" else "link", create_before_publish)
        assert search.copy_legacy_index(source, destination) is False
    assert attempts == [destination]
    assert rows(destination) == [("concurrent.json",)]


@pytest.mark.parametrize("suffix", ["-wal", "-shm", "-journal"])
def test_orphan_destination_sidecar_is_preserved(dirs, suffix):
    new, old = dirs
    source = legacy_index(old)
    destination = new["data"] / "search.db"
    destination.parent.mkdir(parents=True)
    sidecar = Path(str(destination) + suffix)
    sidecar.write_bytes(b"existing recovery data")
    with pytest.raises(FileExistsError):
        search.copy_legacy_index(source, destination)
    assert sidecar.read_bytes() == b"existing recovery data"
    assert not destination.exists()


def test_corrupt_source_is_not_published(dirs):
    new, old = dirs
    source = legacy_index(old)
    source.write_bytes(b"synthetic damaged search database")
    original = source.read_bytes()
    cfg.migrate_legacy_app_data()
    assert not (new["data"] / "search.db").exists()
    assert source.read_bytes() == original
    assert not list(new["data"].glob(".search-migration-*"))


def test_unicode_index_preserves_fts_embeddings_and_metadata(dirs):
    new, old = dirs
    source = legacy_index(old)
    text = "\u0633\u0644\u0627\u0645 \u4e16\u754c"
    transcript = old["data"] / "\u062a\u0633\u062a (1).json"
    transcript.write_text(json.dumps([{"start": 1, "end": 3, "text": text}]), encoding="utf-8")
    with closing(search._open_db(source)) as connection:
        assert search.index_file(str(transcript), conn=connection) == 1
        connection.execute("INSERT INTO embeddings VALUES (?,0,?,2)",
                           (str(transcript), search._vector_to_blob([0.25, 0.75])))
        connection.commit()
    cfg.migrate_legacy_app_data()
    with closing(search._open_db(new["data"] / "search.db")) as connection:
        assert [hit.text for hit in search._fts_query(connection, text, 10)] == [text]
        vector, dim = connection.execute("SELECT vector,dim FROM embeddings").fetchone()
        assert search._blob_to_vector(vector, dim) == [0.25, 0.75]
        assert connection.execute("PRAGMA user_version").fetchone()[0] == search.SCHEMA_VERSION


def test_search_intent_failure_blocks_first_explicit_settings_save(dirs, monkeypatch):
    new, old = dirs
    legacy_index(old)
    write = cfg._write_disk_dict
    attempts = []
    def fail_marker(path, data):
        if Path(path).name == "legacy-search-migration.json":
            attempts.append(path)
            raise OSError(errno.ENOSPC, "synthetic intent failure")
        return write(path, data)
    with monkeypatch.context() as fault:
        fault.setattr(cfg, "_write_disk_dict", fail_marker)
        with pytest.raises(cfg.ConfigSaveError):
            settings = cfg.load_config(fetch_online=False)
            cfg.save_config(settings)
    assert attempts
    assert not (new["config"] / "config.json").exists()
    cfg._legacy_migration_done = False
    cfg.migrate_legacy_app_data()
    assert rows(new["data"] / "search.db") == [("checkpointed.json",)]


@pytest.mark.parametrize("unsupported", [False, True])
def test_link_publication_is_complete_or_leaves_no_target(dirs, monkeypatch, unsupported):
    import os
    from types import SimpleNamespace
    new, old = dirs
    source = legacy_index(old)
    destination = new["data"] / "search.db"
    def refuse_link(*args):
        raise OSError(errno.ENOTSUP, "synthetic unsupported hard links")
    monkeypatch.setattr(search, "os", SimpleNamespace(
        name="posix", path=os.path, link=refuse_link if unsupported else os.link))
    if unsupported:
        with pytest.raises(OSError, match="unsupported hard links"):
            search.copy_legacy_index(source, destination)
        assert not destination.exists()
    else:
        assert search.copy_legacy_index(source, destination)
        assert rows(destination) == [("checkpointed.json",)]
    assert not list(destination.parent.glob(".search-migration-*"))


def test_two_concurrent_snapshot_publishers_keep_one_complete_index(dirs):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    new, old = dirs
    source = legacy_index(old)
    destination = new["data"] / "search.db"
    barrier = Barrier(2)
    def publish():
        barrier.wait(timeout=5)
        return search.copy_legacy_index(source, destination)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: publish(), range(2)))
    assert sorted(results) == [False, True]
    assert rows(destination) == [("checkpointed.json",)]
    assert not list(destination.parent.glob(".search-migration-*"))


def test_snapshot_busy_timeout_leaves_no_public_index(dirs, monkeypatch):
    new, old = dirs
    source = legacy_index(old)
    destination = new["data"] / "search.db"
    clock = iter([0.0, 6.0])
    monkeypatch.setattr(search.time, "monotonic", lambda: next(clock))
    with pytest.raises(TimeoutError, match="timed out"):
        search.copy_legacy_index(source, destination)
    assert not destination.exists()
    assert not list(destination.parent.glob(".search-migration-*"))


def test_special_character_source_uri_and_extended_local_path(dirs):
    import os
    new, old = dirs
    source = legacy_index(old)
    special = source.with_name("search # 100% caf\u00e9.db")
    source.rename(special)
    if os.name == "nt":
        special = Path("\\\\?\\" + str(special.absolute()))
    destination = new["data"] / "search.db"
    assert search.copy_legacy_index(special, destination)
    assert rows(destination) == [("checkpointed.json",)]


def test_network_source_uri_keeps_empty_authority(dirs, monkeypatch):
    import os
    if os.name != "nt":
        return  # Only Windows paths have this UNC spelling.
    from urllib.parse import unquote, urlsplit
    new, _old = dirs
    source = Path("\\\\?\\UNC\\host\\share\\search # 100%.db")
    observed = []
    def inspect_uri(database_uri, *args, **kwargs):
        observed.append(database_uri)
        parsed = urlsplit(database_uri)
        assert parsed.netloc == ""
        assert unquote(parsed.path) == "//host/share/search # 100%.db"
        assert parsed.query == "mode=ro"
        raise OSError(errno.EACCES, "synthetic network refusal")
    monkeypatch.setattr(search.sqlite3, "connect", inspect_uri)
    with pytest.raises(OSError, match="network refusal"):
        search.copy_legacy_index(source, new["data"] / "search.db")
    assert len(observed) == 1
    assert not (new["data"] / "search.db").exists()
