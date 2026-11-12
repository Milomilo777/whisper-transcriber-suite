"""A cleanup retry must preserve the usability of persisted result paths."""
import errno
import json
import sqlite3
from pathlib import Path

import pytest

from core import history
from core.server import jobs as J


@pytest.mark.parametrize("nested", [False, True])
@pytest.mark.parametrize("restart", [False, True])
def test_cleanup_retry_relocates_real_history_before_removing_originals(tmp_path, monkeypatch, nested, restart):
    monkeypatch.setattr(history, "default_db_path", lambda: tmp_path / "history.db")
    job_id = "b" * 32
    work = tmp_path / "jobs" / job_id
    source = work / "captions" / "transcript.srt" if nested else work / "transcript.srt"
    source.parent.mkdir(parents=True)
    complete = b"1\n00:00:00,000 --> 00:00:01,000\nComplete.\n"
    source.write_bytes(complete)
    archive = tmp_path / "outputs"
    manager = J.JobManager(lambda *args, **kwargs: None, jobs_root=str(work.parent),
                           outputs_root=str(archive), record_history=True)
    job = J.Job(job_id, "upload", ["srt"], work_dir=str(work), outputs=[("srt", str(source))])
    db, rid = manager._open_history(job)
    assert db is not None and rid is not None

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic archive failure")

    with monkeypatch.context() as fault:
        fault.setattr(J, "_copy_output_atomic", cannot_copy)
        manager._settle(job, J.STATUS_FINISHED, db, rid, 1.25, "en")
    with history.HistoryDB() as saved:
        before = saved.list_transcriptions()[0]
    assert before["output_paths"] == [str(source)] and source.exists()
    assert before["status"] == "finished" and job.warning == J._UNSAVED_WARNING

    assert manager._discard_dir(str(work), None if restart else job)
    destination = archive / job_id[:12] / source.relative_to(work)
    assert destination.read_bytes() == complete and not work.exists()
    with history.HistoryDB() as saved:
        after = saved.list_transcriptions()[0]
    assert all(Path(path).is_file() for path in after["output_paths"])
    assert after == {**before, "output_paths": [str(destination)]}


@pytest.mark.parametrize("nested", [False, True])
def test_successfully_archived_history_stays_accessible_after_cleanup(tmp_path, monkeypatch, nested):
    monkeypatch.setattr(history, "default_db_path", lambda: tmp_path / "history.db")
    job_id = "c" * 32
    work = tmp_path / "jobs" / job_id
    source = work / "captions" / "transcript.srt" if nested else work / "transcript.srt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"completed result")
    manager = J.JobManager(lambda *args, **kwargs: None, jobs_root=str(work.parent),
                           outputs_root=str(tmp_path / "outputs"), record_history=True)
    job = J.Job(job_id, "upload", ["srt"], work_dir=str(work), outputs=[("srt", str(source))])
    db, rid = manager._open_history(job)
    manager._settle(job, J.STATUS_FINISHED, db, rid, 1.25, "en")
    with history.HistoryDB() as saved:
        before = saved.list_transcriptions()[0]
    assert manager._discard_dir(str(work), None if nested else job)
    with history.HistoryDB() as saved:
        assert saved.list_transcriptions()[0] == before
    assert not work.exists() and all(Path(path).is_file() for path in before["output_paths"])


def _failed_history_job(tmp_path, monkeypatch):
    monkeypatch.setattr(history, "default_db_path", lambda: tmp_path / "history.db")
    job_id = "d" * 32
    work = tmp_path / "jobs" / job_id
    source = work / "captions" / "résumé.srt"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"complete retained result")
    manager = J.JobManager(lambda *args, **kwargs: None, jobs_root=str(work.parent),
                           outputs_root=str(tmp_path / "outputs"), record_history=True)
    job = J.Job(job_id, "upload", ["srt"], work_dir=str(work), outputs=[("srt", str(source))])
    db, rid = manager._open_history(job)

    def cannot_copy(*args, **kwargs):
        raise OSError(errno.ENOSPC, "synthetic archive failure")

    with monkeypatch.context() as fault:
        fault.setattr(J, "_copy_output_atomic", cannot_copy)
        manager._settle(job, J.STATUS_FINISHED, db, rid, 1.25, "en")
    return manager, job, source


@pytest.mark.parametrize("restart", [False, True])
def test_history_commit_failure_keeps_originals_and_retry_repairs_paths(tmp_path, monkeypatch, restart):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    with history.HistoryDB() as saved:
        second_id = saved.insert_transcription("other source", model="tiny", language="fr")
        saved.finish_transcription(second_id, "cancelled", output_paths=[str(source)],
                                    duration_seconds=2.5, error="retained partial")
        before = saved.list_transcriptions()
        # The first row's rewrite must roll back if a later matching row fails.
        with saved._txn() as conn:
            conn.execute("CREATE TRIGGER reject_relocation BEFORE UPDATE OF output_paths "
                         "ON transcriptions WHEN OLD.id = " + str(second_id) +
                         " BEGIN SELECT RAISE(ABORT, 'synthetic history write failure'); END")
    assert not manager._discard_dir(job.work_dir, None if restart else job)
    assert source.read_bytes() == b"complete retained result"
    with history.HistoryDB() as saved:
        assert saved.list_transcriptions() == before
        with saved._txn() as conn:
            conn.execute("DROP TRIGGER reject_relocation")
    assert manager._discard_dir(job.work_dir, None if restart else job)
    with history.HistoryDB() as saved:
        after = saved.list_transcriptions()
    assert all(Path(path).is_file() for row in after for path in row["output_paths"])
    assert all({k: v for k, v in old.items() if k != "output_paths"} ==
               {k: v for k, v in new.items() if k != "output_paths"}
               for old, new in zip(before, after))


def test_history_open_failure_never_authorizes_removing_originals(tmp_path, monkeypatch):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)

    def unavailable(*args, **kwargs):
        raise sqlite3.OperationalError("synthetic history unavailable")

    with monkeypatch.context() as fault:
        fault.setattr(history, "HistoryDB", unavailable)
        assert not manager._discard_dir(job.work_dir)
    assert source.is_file()
    assert manager._discard_dir(job.work_dir)
    with history.HistoryDB() as saved:
        assert all(Path(path).is_file() for path in saved.list_transcriptions()[0]["output_paths"])


def test_restart_with_new_history_recording_disabled_still_repairs_existing_rows(tmp_path, monkeypatch):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    manager._record_history = False
    assert manager._discard_dir(job.work_dir)
    with history.HistoryDB() as saved:
        assert all(Path(path).is_file() for path in saved.list_transcriptions()[0]["output_paths"])


def test_cleanup_without_an_existing_history_database_does_not_create_one(tmp_path, monkeypatch):
    path = tmp_path / "no-history.db"
    monkeypatch.setattr(history, "default_db_path", lambda: path)
    work = tmp_path / "jobs" / ("e" * 32)
    work.mkdir(parents=True)
    source = work / "out.srt"
    source.write_bytes(b"complete result without history")
    manager = J.JobManager(lambda *args, **kwargs: None, jobs_root=str(work.parent),
                           outputs_root=str(tmp_path / "outputs"), record_history=False)
    job = J.Job("e" * 32, "upload", ["srt"], work_dir=str(work), outputs=[("srt", str(source))])
    assert manager._discard_dir(job.work_dir, job)
    assert not path.exists()


def test_retry_repairs_all_history_pages_aliases_and_preserves_other_paths(tmp_path, monkeypatch):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    unrelated = tmp_path / "other-job" / source.name
    unrelated.parent.mkdir()
    unrelated.write_bytes(b"unrelated result")
    alias = str(source.parent) + "/./" + source.name
    with history.HistoryDB() as saved:
        original_id = saved.list_transcriptions()[0]["id"]
        # Both a row older than the viewer's 200-row window and a reference
        # past the first database page must remain usable after cleanup.
        with saved._txn() as conn:
            conn.executemany("INSERT INTO transcriptions (file_path, status, started_at) "
                             "VALUES (?, 'running', 1)", [("other " + str(i),) for i in range(300)])
            conn.execute("UPDATE transcriptions SET output_paths=? WHERE id=?",
                         (json.dumps([alias, str(unrelated), alias], ensure_ascii=False), original_id))
        latest_id = saved.insert_transcription("newer reference", task="translate")
        saved.finish_transcription(latest_id, "cancelled", output_paths=[str(source)],
                                    language="fr", duration_seconds=4, word_count=9, error="retained partial")
        before = saved.list_transcriptions(limit=1000)
    assert manager._discard_dir(job.work_dir)
    destination = Path(manager._outputs_root) / job.job_id[:12] / source.relative_to(Path(job.work_dir))
    with history.HistoryDB() as saved:
        after = saved.list_transcriptions(limit=1000)
    expected = []
    for row in before:
        outputs = row["output_paths"]
        if row["id"] == original_id:
            outputs = [str(destination), str(unrelated), str(destination)]
        elif row["id"] == latest_id:
            outputs = [str(destination)]
        expected.append({**row, "output_paths": outputs})
    assert after == expected
    assert unrelated.read_bytes() == b"unrelated result"
    assert destination.read_bytes() == b"complete retained result"


@pytest.mark.parametrize("damaged", ["{broken", '{"unexpected": []}', "[1]"])
def test_uncertain_history_paths_roll_back_repairs_and_keep_originals(tmp_path, monkeypatch, damaged):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    with history.HistoryDB() as saved:
        original = saved.list_transcriptions()[0]
        other_id = saved.insert_transcription("damaged record")
        with saved._txn() as conn:
            conn.execute("UPDATE transcriptions SET output_paths=? WHERE id=?", (damaged, other_id))
    assert not manager._discard_dir(job.work_dir)
    assert source.is_file()
    with history.HistoryDB() as saved:
        rows = saved.list_transcriptions()
        assert next(row for row in rows if row["id"] == original["id"]) == original
        with saved._txn() as conn:
            conn.execute("UPDATE transcriptions SET output_paths='[]' WHERE id=?", (other_id,))
    assert manager._discard_dir(job.work_dir)
    with history.HistoryDB() as saved:
        row = next(row for row in saved.list_transcriptions() if row["id"] == original["id"])
    assert all(Path(path).is_file() for path in row["output_paths"])


def test_busy_history_writer_keeps_original_until_a_successful_retry(tmp_path, monkeypatch):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    original_class = history.HistoryDB
    opened = original_class()
    opened._conn.execute("PRAGMA busy_timeout=0")
    blocker = sqlite3.connect(str(opened.path))
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with monkeypatch.context() as fault:
            fault.setattr(history, "HistoryDB", lambda *args, **kwargs: opened)
            assert not manager._discard_dir(job.work_dir)
        assert source.is_file()
    finally:
        blocker.rollback()
        blocker.close()
        opened.close()
    assert manager._discard_dir(job.work_dir)
    with original_class() as saved:
        assert all(Path(path).is_file() for path in saved.list_transcriptions()[0]["output_paths"])


def test_relocation_is_durable_while_another_wal_connection_remains_open(tmp_path, monkeypatch):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    original_class = history.HistoryDB
    modes = []
    with original_class() as other:
        assert other._conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"

        def observed(*args, **kwargs):
            opened = original_class(*args, **kwargs)

            def trace(statement):
                if statement == "BEGIN IMMEDIATE":
                    modes.append(opened._conn.execute("PRAGMA synchronous").fetchone()[0])

            opened._conn.set_trace_callback(trace)
            return opened

        with monkeypatch.context() as observation:
            observation.setattr(history, "HistoryDB", observed)
            assert manager._discard_dir(job.work_dir)
        assert modes and all(mode >= 2 for mode in modes)
        assert all(Path(path).is_file() for path in other.list_transcriptions()[0]["output_paths"])


def test_corrupt_database_cleanup_keeps_originals_without_automatic_recovery(tmp_path, monkeypatch):
    manager, job, source = _failed_history_job(tmp_path, monkeypatch)
    path = history.default_db_path()
    healthy = path.read_bytes()
    damaged = b"damaged database still naming " + str(source).encode("utf-8")
    path.write_bytes(damaged)
    names_before = {p.name for p in tmp_path.iterdir()}
    assert not manager._discard_dir(job.work_dir)
    assert source.is_file() and path.read_bytes() == damaged
    assert {p.name for p in tmp_path.iterdir()} == names_before
    path.write_bytes(healthy)
    assert manager._discard_dir(job.work_dir)
    with history.HistoryDB() as saved:
        assert all(Path(p).is_file() for p in saved.list_transcriptions()[0]["output_paths"])
