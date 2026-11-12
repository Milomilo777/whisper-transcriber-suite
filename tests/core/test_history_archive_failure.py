"""A failed recovery archive must not destroy salvageable history."""
import errno
import sqlite3
from pathlib import Path

import pytest

from core.history import HistoryDB
from core import history


@pytest.fixture
def damaged_history(tmp_path):
    path = tmp_path / "history.db"
    with HistoryDB(path) as db:
        db.insert_download("https://example.invalid/recoverable", title="Keep this history")
    original = path.read_bytes()
    damaged = b"DAMAGED HEADER!!" + original[16:]
    path.write_bytes(damaged)
    return path, original, damaged


@pytest.mark.parametrize("code", [errno.EACCES, errno.ENOSPC])
def test_failed_archive_preserves_recoverable_history(damaged_history, monkeypatch, code):
    path, original, damaged = damaged_history
    copy = history.shutil.copyfileobj

    def fail_archive(source, destination, *args):
        if Path(source.name) == path:
            raise OSError(code, "synthetic archive failure")
        return copy(source, destination, *args)

    with monkeypatch.context() as failure:
        failure.setattr(history.shutil, "copyfileobj", fail_archive)
        error = None
        try:
            HistoryDB(path).close()
        except sqlite3.DatabaseError as caught:
            error = caught
    assert path.read_bytes() == damaged
    assert not list(path.parent.glob("*.corrupt.*"))
    assert error is not None and "preserv" in str(error)
    # Restoring just the header proves these bytes still hold recoverable rows.
    path.write_bytes(original[:16] + path.read_bytes()[16:])
    with HistoryDB(path) as repaired:
        assert repaired.list_downloads()[0]["title"] == "Keep this history"


def test_archive_can_retry_after_failure_without_losing_original(damaged_history, monkeypatch):
    path, _original, damaged = damaged_history
    copy = history.shutil.copyfileobj

    def fail_archive(source, destination, *args):
        if Path(source.name) == path:
            raise PermissionError("synthetic sharing failure")
        return copy(source, destination, *args)

    with monkeypatch.context() as failure:
        failure.setattr(history.shutil, "copyfileobj", fail_archive)
        with pytest.raises(sqlite3.DatabaseError):
            HistoryDB(path)
    with HistoryDB(path) as recovered:
        assert recovered.list_downloads() == []
        recovered.insert_download("https://example.invalid/new")
    archives = list(path.parent.glob("history.db.corrupt.*"))
    assert len(archives) == 1 and archives[0].read_bytes() == damaged
    with HistoryDB(path) as reopened:
        assert reopened.list_downloads()[0]["url"] == "https://example.invalid/new"
