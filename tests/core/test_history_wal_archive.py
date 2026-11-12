"""Retain committed SQLite WAL transactions when recovery cannot archive a file."""
import os
from urllib.parse import unquote, urlsplit
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from core.history import HistoryDB
from core import history


@pytest.fixture
def crashed_history(tmp_path):
    path = tmp_path / "history.db"
    with HistoryDB(path):
        pass
    code = """
import os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.execute('PRAGMA journal_mode=WAL')
db.execute('PRAGMA wal_autocheckpoint=0')
db.execute("INSERT INTO downloads(url, title, status) VALUES(?, ?, 'done')",
           ('https://example.invalid/committed', 'Committed only in WAL'))
db.commit()
os._exit(0)
"""
    subprocess.run(
        [sys.executable, "-c", code, str(path)], check=True, timeout=15,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )
    wal = Path(str(path) + "-wal")
    assert wal.stat().st_size > 32
    header = path.read_bytes()[:16]
    path.write_bytes(b"DAMAGED HEADER!!" + path.read_bytes()[16:])
    return path, wal, header, wal.read_bytes()


def assert_committed_row_survives(path, header):
    path.write_bytes(header + path.read_bytes()[16:])
    with sqlite3.connect(str(path)) as repaired:
        row = repaired.execute("SELECT title FROM downloads").fetchone()
        assert row == ("Committed only in WAL",)


def test_real_crash_wal_survives_archive_copy_failure(crashed_history, monkeypatch):
    path, wal, header, wal_bytes = crashed_history
    copy = history.shutil.copyfileobj

    def deny_wal_copy(source, destination, *args):
        if Path(source.name) == wal:
            raise PermissionError("synthetic WAL archive denial")
        return copy(source, destination, *args)

    with monkeypatch.context() as failure:
        failure.setattr(history.shutil, "copyfileobj", deny_wal_copy)
        try:
            HistoryDB(path).close()
        except sqlite3.DatabaseError:
            pass
    archives = [p for p in path.parent.glob("history.db.corrupt.*")
                if not p.name.endswith(("-wal", "-shm"))]
    candidates = [p for p in [wal, *path.parent.glob("history.db.corrupt.*-wal")]
                  if p.exists() and p.read_bytes() == wal_bytes]
    assert candidates, "recovery deleted the only committed WAL instead of preserving it"
    recovery_path = path if wal in candidates else archives[0]
    assert_committed_row_survives(recovery_path, header)


def test_normal_recovery_retains_real_committed_wal(crashed_history):
    path, _wal, header, wal_bytes = crashed_history
    with HistoryDB(path) as fresh:
        assert fresh.list_downloads() == []
    archives = [p for p in path.parent.glob("history.db.corrupt.*")
                if not p.name.endswith(("-wal", "-shm"))]
    assert len(archives) == 1
    assert Path(str(archives[0]) + "-wal").read_bytes() == wal_bytes
    assert_committed_row_survives(archives[0], header)


def test_wal_sync_failure_keeps_original_committed_rows(crashed_history, monkeypatch):
    from core import _checkpoint

    path, wal, header, wal_bytes = crashed_history
    sync = _checkpoint._strict_sync

    def fail_wal_sync(stream):
        if str(stream.name).endswith("-wal"):
            raise OSError("synthetic WAL sync failure")
        sync(stream)

    monkeypatch.setattr(_checkpoint, "_strict_sync", fail_wal_sync)
    with pytest.raises(sqlite3.DatabaseError, match="preserv"):
        HistoryDB(path)
    assert wal.read_bytes() == wal_bytes
    assert not list(path.parent.glob("history.db.corrupt.*"))
    assert_committed_row_survives(path, header)


@pytest.mark.parametrize("blocked_suffix", ["-wal", "-shm", ""])
def test_failed_original_removal_keeps_complete_archive(crashed_history, monkeypatch, blocked_suffix):
    path, _wal, header, wal_bytes = crashed_history
    unlink = os.unlink

    def block_original_removal(source, *args, **kwargs):
        if str(source) == str(path) + blocked_suffix:
            raise PermissionError("synthetic original isolation failure")
        return unlink(source, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", block_original_removal)
    with pytest.raises(sqlite3.DatabaseError, match="preserved"):
        HistoryDB(path)
    assert path.exists()
    archives = [p for p in path.parent.glob("history.db.corrupt.*")
                if not p.name.endswith(("-wal", "-shm"))]
    assert len(archives) == 1
    assert Path(str(archives[0]) + "-wal").read_bytes() == wal_bytes
    assert_committed_row_survives(archives[0], header)


def test_archive_collision_preserves_existing_archive_and_original(crashed_history, monkeypatch):
    path, wal, _header, wal_bytes = crashed_history
    foreign = path.parent / "older-history-archive"
    foreign.write_bytes(b"previous recoverable history")
    monkeypatch.setattr(history, "_unique_archive_path", lambda _: str(foreign))
    with pytest.raises(sqlite3.DatabaseError, match="preserv"):
        HistoryDB(path)
    assert foreign.read_bytes() == b"previous recoverable history"
    assert wal.read_bytes() == wal_bytes


def test_healthy_crash_wal_is_read_without_archiving(crashed_history):
    path, _wal, header, _wal_bytes = crashed_history
    path.write_bytes(header + path.read_bytes()[16:])
    with HistoryDB(path) as healthy:
        assert healthy.list_downloads()[0]["title"] == "Committed only in WAL"
    assert not list(path.parent.glob("history.db.corrupt.*"))


def test_other_instance_ownership_blocks_recovery_without_touching_data(tmp_path):
    path = tmp_path / "history.db"
    owner = HistoryDB(path)
    assert owner.claim_instance_lock()
    owner._conn.close()
    original = path.read_bytes()
    damaged = b"DAMAGED HEADER!!" + original[16:]
    path.write_bytes(damaged)
    try:
        with pytest.raises(sqlite3.DatabaseError, match="another instance"):
            HistoryDB(path)
        assert path.read_bytes() == damaged
        assert not list(tmp_path.glob("history.db.corrupt.*"))
    finally:
        owner.close()


def test_readonly_preflight_supports_encoded_filename(tmp_path):
    path = tmp_path / "history # 100% café.db"
    with HistoryDB(path) as db:
        db.insert_download("https://example.invalid/encoded")
    with HistoryDB(path) as reopened:
        assert reopened.list_downloads()[0]["url"] == "https://example.invalid/encoded"


def test_corrupt_btree_page_recovery_retains_committed_wal(crashed_history):
    path, _wal, header, wal_bytes = crashed_history
    path.write_bytes(header + path.read_bytes()[16:])
    with sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True) as probe:
        page = probe.execute(
            "SELECT rootpage FROM sqlite_master WHERE name='transcriptions'"
        ).fetchone()[0]
        page_size = probe.execute("PRAGMA page_size").fetchone()[0]
    probe.close()
    raw = path.read_bytes()
    offset = (page - 1) * page_size
    original_page_type = raw[offset:offset + 1]
    path.write_bytes(raw[:offset] + b"\xff" + raw[offset + 1:])
    with HistoryDB(path) as fresh:
        assert fresh.list_downloads() == []
    archives = [p for p in path.parent.glob("history.db.corrupt.*")
                if not p.name.endswith(("-wal", "-shm"))]
    assert len(archives) == 1
    archive = archives[0]
    assert Path(str(archive) + "-wal").read_bytes() == wal_bytes
    damaged = archive.read_bytes()
    archive.write_bytes(damaged[:offset] + original_page_type + damaged[offset + 1:])
    with sqlite3.connect(archive) as repaired:
        assert repaired.execute("SELECT title FROM downloads").fetchone() == (
            "Committed only in WAL",
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows UNC URI conversion")
@pytest.mark.parametrize("name", ["history.db", "history # 100% café.db"])
def test_extended_unc_readonly_uri_retains_network_root(name):
    extended = "\\\\?\\UNC\\host\\share\\" + name
    ordinary = "\\\\host\\share\\" + name
    uri = history._read_only_uri(extended)
    assert uri == history._read_only_uri(ordinary)
    assert uri.startswith("file:////host/share/")
    assert uri.endswith("?mode=ro")
    parsed = urlsplit(uri)
    assert parsed.netloc == ""
    assert unquote(parsed.path) == ordinary.replace("\\", "/")


@pytest.mark.skipif(os.name != "nt", reason="Windows extended local paths")
@pytest.mark.parametrize("name", ["history.db", "history # 100% café.db"])
def test_extended_local_readonly_uri_opens_same_database_and_refuses_writes(tmp_path, name):
    path = tmp_path / name
    writer = sqlite3.connect(path)
    try:
        writer.execute("CREATE TABLE words (text TEXT)")
        writer.execute("INSERT INTO words VALUES ('retained')")
        writer.commit()
    finally:
        writer.close()
    extended = "\\\\?\\" + str(path.resolve())
    uri = history._read_only_uri(extended)
    reader = sqlite3.connect(uri, uri=True)
    try:
        assert reader.execute("SELECT text FROM words").fetchall() == [("retained",)]
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            reader.execute("INSERT INTO words VALUES ('unexpected')")
    finally:
        reader.close()
