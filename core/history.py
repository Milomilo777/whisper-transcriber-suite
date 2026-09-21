"""SQLite history of downloads + transcriptions.

Schema is created on first open and is idempotent. Database lives at
``user_data_dir() / "history.db"``. Calls are cheap (one connection per
HistoryDB instance) and use ``with conn`` blocks to commit-or-rollback.

The Tk app does not call this from the main thread for long queries — but
small writes (insert / mark_finished / mark_interrupted) are fast enough.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable

from .config import user_data_dir

logger = logging.getLogger(__name__)


SCHEMA = """
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
CREATE INDEX IF NOT EXISTS idx_downloads_status ON downloads(status);
CREATE INDEX IF NOT EXISTS idx_transcriptions_status ON transcriptions(status);
"""


def default_db_path() -> Path:
    return user_data_dir() / "history.db"


def _is_transient_lock_error(exc: sqlite3.Error) -> bool:
    """True when ``exc`` is lock contention, NOT on-disk corruption.

    ``SQLITE_BUSY`` / ``SQLITE_LOCKED`` only mean another connection (the
    GUI plus a second app instance, or a worker) currently holds the DB;
    the file itself can be perfectly healthy. Treating a lock as
    corruption would rename a good ``history.db`` to ``.corrupt`` and
    recreate it empty — silently losing the user's entire history
    because two processes overlapped for a moment. The error *name* is
    authoritative (``sqlite3`` attaches it on 3.11+); the message check
    is a fallback for manually-constructed errors.
    """
    name = str(getattr(exc, "sqlite_errorname", "") or "")
    if name.startswith(("SQLITE_BUSY", "SQLITE_LOCKED")):
        return True
    message = str(exc).lower()
    return (
        "database is locked" in message
        or "database table is locked" in message
        or "database schema is locked" in message
    )


class HistoryDB:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path: Path = Path(path) if path else default_db_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False — the transcription / download
        # services dispatch from worker threads, not the Tk main
        # thread. Without this flag every cross-thread insert
        # raises sqlite3.ProgrammingError (silently swallowed by
        # the callers' broad `except Exception`), so the entire
        # history is empty in real usage.
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        # Module-level write lock — SQLite serialises writes
        # internally but the Python connection object is not
        # thread-safe for concurrent write attempts; the lock
        # gives us deterministic queue + commit semantics.
        self._write_lock = threading.Lock()
        # WAL mode (audit D2): the default DELETE journal locks the
        # whole DB during writes, starves concurrent readers, and on
        # a hard crash mid-write can leave the file unopenable on
        # the next launch. WAL allows concurrent read while a write
        # is in-flight and recovers automatically. NORMAL sync is
        # the standard trade-off — slightly weaker durability than
        # FULL but avoids fsync on every commit (history.db can
        # afford to lose the last few inserts on a kernel-panic).
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error as e:
            logger.exception("history.db PRAGMA setup failed: %s", e)
        # Integrity check on open (audit D6) — a crash-corrupted DB
        # is detected up front and renamed aside so the user gets
        # a fresh-but-empty history instead of a launch crash.
        self._check_integrity_or_recover()
        with self._conn:
            self._conn.executescript(SCHEMA)
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Idempotent ADD COLUMN migrations guarded by a PRAGMA table_info
        check (SQLite has no ``ADD COLUMN IF NOT EXISTS``). Safe to run on
        every open: a column already present is skipped.

        P4-4: ``transcriptions.word_count`` — total words in the produced
        transcript text (INTEGER, default 0), populated by
        ``finish_transcription``.
        """
        try:
            cols = {
                row[1]
                for row in self._conn.execute(
                    "PRAGMA table_info(transcriptions)"
                ).fetchall()
            }
            if "word_count" not in cols:
                with self._conn:
                    self._conn.execute(
                        "ALTER TABLE transcriptions "
                        "ADD COLUMN word_count INTEGER DEFAULT 0"
                    )
        except sqlite3.Error as e:
            logger.exception("history.db word_count migration failed: %s", e)

    def _check_integrity_or_recover(self) -> None:
        """Run ``PRAGMA integrity_check``. On a non-``ok`` result, close the
        connection, rename the DB to ``.corrupt``, and recreate it fresh. The
        user loses history but the app launches; trade-off chosen over a
        launch crash.

        A badly-mangled file makes the PRAGMA itself raise
        ``sqlite3.DatabaseError`` ("file is not a database") rather than
        returning a non-``ok`` row — that is ALSO corruption and must trigger
        the same recover-aside, otherwise __init__ would fall through to
        ``executescript(SCHEMA)`` and crash on the malformed file at launch.

        A LOCK error is deliberately NOT corruption (see
        :func:`_is_transient_lock_error`): another connection merely holding
        the DB must never cost the user their history.
        """
        try:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.Error as e:
            if _is_transient_lock_error(e):
                logger.warning(
                    "history.db is locked by another connection (%s); "
                    "skipping this open's integrity_check instead of "
                    "treating a healthy DB as corrupt.", e,
                )
                return
            logger.error(
                "history.db integrity_check raised (%s); treating as "
                "corruption and recovering.", e,
            )
            self._recover_corrupt_db(str(e))
            return
        if row is None:
            return
        result = (str(row[0]) if not hasattr(row, "keys")
                  else str(list(row)[0])).lower()
        if result == "ok":
            return
        logger.error(
            "history.db failed integrity_check (%s); renaming to "
            ".corrupt and recreating.", result,
        )
        self._recover_corrupt_db(result)

    def _recover_corrupt_db(self, reason: str) -> None:
        """Move the corrupt DB (and its WAL/SHM sidecars) aside and reopen a
        fresh one. Never raises — the goal is to always leave ``self._conn``
        pointing at a usable, clean database so __init__ can build the schema.
        """
        logger.debug("history.db recovery starting (reason=%s)", reason)
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
        import os as _os
        corrupt_path = str(self.path) + ".corrupt"
        moved_main = False
        try:
            if _os.path.exists(corrupt_path):
                _os.unlink(corrupt_path)
            _os.replace(str(self.path), corrupt_path)
            moved_main = True
        except OSError as e:
            logger.error("Could not move corrupt history.db aside: %s", e)
        # WAL mode was enabled before the integrity check, so the
        # ``-wal`` / ``-shm`` sidecars exist next to the corrupt DB. If
        # they are left behind, SQLite may try to recover/checkpoint them
        # into the fresh DB (salt/checksum mismatch can re-introduce
        # malformed frames). Move them aside with the corrupt main file,
        # or delete them when that is not possible.
        for ext in ("-wal", "-shm"):
            side = str(self.path) + ext
            try:
                if moved_main:
                    _os.replace(side, corrupt_path + ext)
                else:
                    _os.unlink(side)
            except OSError:
                try:
                    _os.unlink(side)
                except OSError:
                    pass
        # If the main DB could NOT be moved aside (e.g. a Windows file
        # lock on os.replace), do not silently reopen the still-corrupt
        # file — reopening it and running executescript() on a malformed
        # DB raises an uncaught DatabaseError in __init__ and crashes the
        # app on launch. Delete it in place so a clean DB is created.
        if not moved_main:
            try:
                _os.unlink(str(self.path))
            except OSError as e:
                logger.error(
                    "Could not delete corrupt history.db in place: %s", e
                )
        # Reopen fresh.
        self._conn = sqlite3.connect(
            str(self.path), check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
        except sqlite3.Error:
            pass

    def close(self) -> None:
        try:
            self._conn.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> "HistoryDB":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    @contextmanager
    def _txn(self):
        # Serialise all writes through _write_lock so concurrent
        # worker-thread inserts (transcription + download services
        # both fire from background threads) never trample each
        # other's commit boundaries.
        try:
            with self._write_lock, self._conn:
                yield self._conn
        except sqlite3.Error as e:
            logger.error("history.db transaction failed: %s", e)
            raise

    # ----- downloads --------------------------------------------------

    def insert_download(self, url: str, title: str = "", folder: str = "",
                        format_label: str = "", started_at: int | None = None) -> int:
        started_at = started_at if started_at is not None else int(time.time())
        with self._txn() as conn:
            cur = conn.execute(
                "INSERT INTO downloads (url, title, folder, format_label, status, started_at)"
                " VALUES (?, ?, ?, ?, 'running', ?)",
                (url, title, folder, format_label, started_at),
            )
            return int(cur.lastrowid or 0)

    def finish_download(self, row_id: int, status: str,
                        output_paths: Iterable[str] = (),
                        detected_language: str = "",
                        error: str = "") -> None:
        paths_json = json.dumps(list(output_paths))
        with self._txn() as conn:
            conn.execute(
                "UPDATE downloads SET status=?, finished_at=?, output_paths=?,"
                " detected_language=?, error=? WHERE id=?",
                (status, int(time.time()), paths_json, detected_language, error, row_id),
            )

    def list_downloads(self, limit: int = 200) -> list[dict[str, Any]]:
        # Serialise the read through _write_lock (same rationale as
        # stats()): list_* runs on the Tk main thread while download /
        # transcription worker threads concurrently run insert_/finish_
        # on the SAME shared self._conn. Two simultaneous executes on one
        # sqlite3.Connection are documented-unsafe and can raise
        # sqlite3.ProgrammingError or return a half-stepped result set.
        with self._write_lock:
            cur = self._conn.execute(
                "SELECT * FROM downloads ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [_row_to_dict(r, ("output_paths",)) for r in cur.fetchall()]

    # ----- transcriptions ---------------------------------------------

    def insert_transcription(self, file_path: str, model: str = "",
                             started_at: int | None = None,
                             language: str = "") -> int:
        started_at = started_at if started_at is not None else int(time.time())
        with self._txn() as conn:
            cur = conn.execute(
                "INSERT INTO transcriptions (file_path, model, status, started_at, language)"
                " VALUES (?, ?, 'running', ?, ?)",
                (file_path, model, started_at, language),
            )
            return int(cur.lastrowid or 0)

    def finish_transcription(self, row_id: int, status: str,
                             output_paths: Iterable[str] = (),
                             duration_seconds: float = 0.0,
                             language: str = "",
                             error: str = "",
                             word_count: int = 0) -> None:
        paths_json = json.dumps(list(output_paths))
        with self._txn() as conn:
            conn.execute(
                "UPDATE transcriptions SET status=?, finished_at=?,"
                " output_paths=?, duration_seconds=?, language=?, error=?,"
                " word_count=? WHERE id=?",
                (status, int(time.time()), paths_json, duration_seconds,
                 language, error, int(word_count or 0), row_id),
            )

    def list_transcriptions(self, limit: int = 200) -> list[dict[str, Any]]:
        # Serialise the read through _write_lock — see list_downloads().
        with self._write_lock:
            cur = self._conn.execute(
                "SELECT * FROM transcriptions ORDER BY id DESC LIMIT ?", (limit,)
            )
            return [_row_to_dict(r, ("output_paths",)) for r in cur.fetchall()]

    # ----- maintenance -------------------------------------------------

    def mark_interrupted(self) -> int:
        """Move every still-running row to ``interrupted``. Returns rows touched."""
        with self._txn() as conn:
            d = conn.execute(
                "UPDATE downloads SET status='interrupted' WHERE status IN ('running','waiting')"
            ).rowcount
            t = conn.execute(
                "UPDATE transcriptions SET status='interrupted' WHERE status IN ('running','waiting')"
            ).rowcount
        return int(d) + int(t)

    def dismiss_interrupted_transcriptions(self, row_ids: Iterable[int]) -> int:
        """Move the given interrupted transcription rows to ``cancelled``.

        Crash-resume offers interrupted rows once per launch. Without
        this, clicking "No" left them ``interrupted`` so the same
        prompt reappeared on every later launch — the only way to
        clear it was to actually re-run the transcription. Marking the
        declined rows ``cancelled`` (a terminal status the resume scan
        skips and ``stats`` does not count) stops the nag while keeping
        the row in history. Returns rows touched.
        """
        ids = [int(i) for i in row_ids]
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._txn() as conn:
            n = conn.execute(
                "UPDATE transcriptions SET status='cancelled' "
                f"WHERE status='interrupted' AND id IN ({placeholders})",
                ids,
            ).rowcount
        return int(n)

    def stats(self) -> dict[str, Any]:
        """Quick stats for the Statistics dialog.

        Audit A10: this method spans 6 SELECTs. Without holding a
        consistent snapshot, a concurrent insert could land between
        two of them and produce inconsistent totals (downloads_total
        less than downloads_finished, etc.). Take the write lock for
        the read so every statement sees the same DB version.
        """
        with self._write_lock:
            rows = {}
            rows["downloads_total"] = self._conn.execute(
                "SELECT COUNT(*) FROM downloads"
            ).fetchone()[0]
            rows["downloads_finished"] = self._conn.execute(
                "SELECT COUNT(*) FROM downloads WHERE status='finished'"
            ).fetchone()[0]
            rows["transcriptions_total"] = self._conn.execute(
                "SELECT COUNT(*) FROM transcriptions"
            ).fetchone()[0]
            rows["transcriptions_finished"] = self._conn.execute(
                "SELECT COUNT(*) FROM transcriptions WHERE status='finished'"
            ).fetchone()[0]
            rows["transcription_minutes"] = round(
                (self._conn.execute(
                    "SELECT COALESCE(SUM(duration_seconds), 0) FROM transcriptions WHERE status='finished'"
                ).fetchone()[0] or 0) / 60.0,
                1,
            )
            top_langs = self._conn.execute(
                "SELECT language, COUNT(*) c FROM transcriptions "
                "WHERE status='finished' AND language != '' "
                "GROUP BY language ORDER BY c DESC LIMIT 5"
            ).fetchall()
            rows["top_languages"] = [(r[0], int(r[1])) for r in top_langs]
            return rows


def _row_to_dict(row: sqlite3.Row, json_fields: tuple[str, ...]) -> dict[str, Any]:
    out = dict(row)
    for key in json_fields:
        raw = out.get(key)
        if raw:
            try:
                out[key] = json.loads(raw)
            except (TypeError, ValueError):
                pass
    return out
