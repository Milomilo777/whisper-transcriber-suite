"""Tests for core.logging_setup — per-process worker log files + cleanup."""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from core import logging_setup as ls


def _touch(path: Path, age_days: float) -> Path:
    path.write_text("x", encoding="utf-8")
    ts = time.time() - age_days * 24 * 60 * 60
    os.utime(path, (ts, ts))
    return path


def _run_setup_logging(tmp_path, monkeypatch) -> None:
    """Call setup_logging against tmp_path and detach the handlers after."""
    monkeypatch.setattr(ls, "user_log_dir", lambda: tmp_path)
    monkeypatch.setattr(ls, "_configured", False)
    root = logging.getLogger()
    before = list(root.handlers)
    try:
        ls.setup_logging("INFO")
    finally:
        for handler in list(root.handlers):
            if handler not in before:
                root.removeHandler(handler)
                try:
                    handler.close()
                except Exception:  # noqa: BLE001
                    pass


def test_prune_removes_only_stale_worker_logs(tmp_path, monkeypatch):
    """Worker logs beyond the retention window are pruned; the newest
    WORKER_LOG_KEEP worker logs, app.log and unrelated files survive."""
    # getattr default keeps this test failing on BEHAVIOUR (stale logs
    # survive) rather than at import on the pre-fix code.
    keep = getattr(ls, "WORKER_LOG_KEEP", 10)
    recent = [_touch(tmp_path / f"worker-{i}.log", 1.0) for i in range(keep)]
    old = _touch(tmp_path / "worker-900.log", 30.0)
    old_rotated = _touch(tmp_path / "worker-900.log.1", 30.0)
    old_voiceclone = _touch(tmp_path / "voiceclone-worker-901.log", 30.0)
    app_log = _touch(tmp_path / "app.log", 30.0)
    unrelated = _touch(tmp_path / "notes.log", 30.0)

    _run_setup_logging(tmp_path, monkeypatch)

    for path in recent:
        assert path.exists(), f"recent worker log was pruned: {path.name}"
    assert not old.exists()
    assert not old_rotated.exists()
    assert not old_voiceclone.exists()
    assert app_log.exists(), "the GUI's own app.log must never be pruned"
    assert unrelated.exists(), "non-worker files must never be pruned"


def test_prune_ignores_unrelated_file_containing_worker(tmp_path, monkeypatch):
    """Only the two known producer names (worker-<pid>.log,
    voiceclone-worker-<pid>.log) are ever prune candidates. An unrelated
    file that merely contains "worker-" must survive even when stale and
    past the keep window — the old "*worker-*.log*" glob deleted it."""
    keep = getattr(ls, "WORKER_LOG_KEEP", 10)
    recent = [_touch(tmp_path / f"worker-{i}.log", 1.0) for i in range(keep)]
    caught_out = _touch(tmp_path / "reworker-output.log", 30.0)

    _run_setup_logging(tmp_path, monkeypatch)

    for path in recent:
        assert path.exists(), f"recent worker log was pruned: {path.name}"
    assert caught_out.exists(), (
        "unrelated file containing 'worker-' must never be pruned"
    )


def test_prune_keeps_old_worker_logs_inside_the_keep_window(tmp_path, monkeypatch):
    """Even a very old worker log is kept while it is one of the newest
    WORKER_LOG_KEEP files, so a long-lived process's live log can't be
    unlinked out from under it."""
    olds = [_touch(tmp_path / f"worker-{i}.log", 60.0) for i in range(3)]

    _run_setup_logging(tmp_path, monkeypatch)

    for path in olds:
        assert path.exists(), f"worker log inside the keep window was pruned: {path.name}"


def _fresh_logs(tmp_path, n: int, size: int = 1) -> list[Path]:
    """worker-0..n-1 logs, all recent; index 0 is the newest."""
    out = []
    for i in range(n):
        p = tmp_path / f"worker-{1000 + i}.log"
        p.write_text("x" * size, encoding="utf-8")
        ts = time.time() - (i + 1) * 60
        os.utime(p, (ts, ts))
        out.append(p)
    return out


def test_prune_caps_the_number_of_recent_worker_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "WORKER_LOG_MAX_FILES", 14)
    logs = _fresh_logs(tmp_path, 25)

    _run_setup_logging(tmp_path, monkeypatch)

    alive = [p for p in logs if p.exists()]
    assert alive == logs[:14], "the oldest logs go first, the newest 14 stay"


def test_prune_caps_the_total_bytes_of_worker_logs(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "WORKER_LOG_MAX_BYTES", 12 * 100)
    logs = _fresh_logs(tmp_path, 20, size=100)

    _run_setup_logging(tmp_path, monkeypatch)

    alive = [p for p in logs if p.exists()]
    assert alive == logs[:12]
    assert len(alive) >= ls.WORKER_LOG_KEEP


def test_prune_never_removes_this_process_log(tmp_path, monkeypatch):
    monkeypatch.setattr(ls, "WORKER_LOG_MAX_FILES", 12)
    logs = _fresh_logs(tmp_path, 20)
    own = tmp_path / f"worker-{os.getpid()}.log"
    own_rotated = tmp_path / f"worker-{os.getpid()}.log.1"
    for p in (own, own_rotated):
        p.write_text("x", encoding="utf-8")
        ts = time.time() - 90 * 24 * 60 * 60
        os.utime(p, (ts, ts))

    _run_setup_logging(tmp_path, monkeypatch)

    assert own.exists() and own_rotated.exists()
    assert not logs[-1].exists()


def test_formatter_does_not_cache_an_unredacted_traceback_on_the_record():
    try:
        raise ValueError("https://user:secret@example.org/path")
    except ValueError:
        import sys

        record = logging.LogRecord("t", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    out = ls.RedactingFormatter("%(message)s").format(record)
    assert "secret" not in out
    assert record.exc_text is None
