"""Migration and settings writers serialize without replacing recovery bytes."""
import contextlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from core import config as cfg


@pytest.fixture
def migration(tmp_path, monkeypatch):
    folder = tmp_path / "profile"
    folder.mkdir()
    source, target = tmp_path / "legacy.json", folder / "config.json"
    original = b'{"theme":"dark","old_choice":"keep"}'
    source.write_bytes(original)
    monkeypatch.setattr(cfg, "user_config_dir", lambda: folder)
    monkeypatch.setattr(cfg, "config_path", lambda: str(target))
    monkeypatch.setattr(cfg, "_legacy_config_path", lambda: str(source))
    monkeypatch.setattr(cfg, "_profile_root", lambda: None)
    return source, target, original


def run_interleaving(monkeypatch, pause, second):
    """Let B finish before A resumes, or wait for A's real writer lock.

    The lock observer only releases the barrier if A actually holds the lock.
    Thus the original unlocked implementation runs B completely first, while
    the repaired implementation proves B reached the held writer lock before
    allowing A to finish. All data operations use real temporary files.
    """
    entered, release = threading.Event(), threading.Event()
    a_holds_lock = threading.Event()
    failures = []
    real_lock = cfg._SAVE_LOCK

    class ObservedLock:
        def __enter__(self):
            is_a = threading.current_thread().name == "migration-A"
            if not is_a and a_holds_lock.is_set():
                release.set()
            real_lock.acquire()
            if is_a:
                a_holds_lock.set()

        def __exit__(self, *args):
            if threading.current_thread().name == "migration-A":
                a_holds_lock.clear()
            real_lock.release()

    monkeypatch.setattr(cfg, "_SAVE_LOCK", ObservedLock())

    def checkpoint():
        entered.set()
        assert release.wait(5), "second migration did not reach its checkpoint"

    pause(checkpoint)

    def first():
        try:
            cfg.migrate_config_location()
        except BaseException as error:
            failures.append(error)

    def other():
        try:
            second()
        except BaseException as error:
            failures.append(error)
        finally:
            release.set()

    a = threading.Thread(target=first, name="migration-A")
    b = threading.Thread(target=other, name="migration-B")
    a.start()
    try:
        assert entered.wait(5), "first migration did not reach its checkpoint"
        b.start()
    finally:
        if b.ident is not None:
            b.join(8)
        release.set()
        a.join(8)
    assert not a.is_alive() and not b.is_alive()
    assert not failures, failures


def test_late_migration_never_deletes_other_migrations_backup(migration, monkeypatch):
    source, target, original = migration
    exists = cfg.os.path.exists

    def pause(checkpoint):
        fired = False

        def checked(path):
            nonlocal fired
            value = exists(path)
            if (os.fspath(path) == str(source) and value and not fired
                    and threading.current_thread().name == "migration-A"):
                fired = True
                checkpoint()
            return value

        monkeypatch.setattr(cfg.os.path, "exists", checked)

    run_interleaving(monkeypatch, pause, cfg.migrate_config_location)
    assert target.read_bytes() == original
    assert Path(str(source) + ".migrated.bak").read_bytes() == original
    assert not source.exists()


def test_staged_migration_never_overwrites_newer_settings(migration, monkeypatch):
    source, target, original = migration
    copy = cfg.shutil.copy2
    current = {"theme": "light", "new_choice": "keep"}

    def pause(checkpoint):
        def copied(src, dst, *args, **kwargs):
            result = copy(src, dst, *args, **kwargs)
            if Path(src) == source and threading.current_thread().name == "migration-A":
                checkpoint()
            return result

        monkeypatch.setattr(cfg.shutil, "copy2", copied)

    def save_new():
        cfg.migrate_config_location()
        cfg.save_config(current)

    run_interleaving(monkeypatch, pause, save_new)
    assert json.loads(target.read_bytes()) == current
    assert Path(str(source) + ".migrated.bak").read_bytes() == original
    assert not list(target.parent.glob(".migration-*.tmp"))


@pytest.mark.parametrize("hardlink", [False, True])
def test_existing_recovery_backup_and_new_legacy_are_both_retained(
    migration, hardlink,
):
    source, target, original = migration
    backup = Path(str(source) + ".migrated.bak")
    older = b'{"older_original":"irreplaceable"}'
    if hardlink:
        anchor = source.with_name("older-original.json")
        anchor.write_bytes(older)
        os.link(anchor, backup)
    else:
        backup.write_bytes(older)
    cfg.migrate_config_location()
    assert target.read_bytes() == original
    assert backup.read_bytes() == older
    assert source.read_bytes() == original


def test_busy_migration_keeps_original_and_reports_failure(migration, monkeypatch, caplog):
    source, target, original = migration

    @contextlib.contextmanager
    def busy(*args, **kwargs):
        raise cfg.ConfigBusyError("synthetic competing settings writer")
        yield

    monkeypatch.setattr(cfg, "_config_file_lock", busy)
    assert cfg.migrate_config_location() == str(target)
    assert source.read_bytes() == original
    assert not target.exists()
    assert "migrat" in caplog.text.lower()


def test_other_process_settings_lock_blocks_migration(migration, monkeypatch, caplog):
    source, target, original = migration
    script = (
        "import sys; from core import config as cfg; "
        "lock=cfg._config_file_lock(sys.argv[1]); "
        "lock.__enter__(); print('locked', flush=True); "
        "sys.stdin.readline(); lock.__exit__(None,None,None)"
    )
    # The child only imports config and locks this test's temporary file.
    child = subprocess.Popen(
        [sys.executable, "-B", "-c", script, str(target)],
        cwd=Path(__file__).resolve().parents[2],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    ready = threading.Event()
    messages = []

    def read_ready():
        assert child.stdout is not None
        messages.append(child.stdout.readline().strip())
        ready.set()

    reader = threading.Thread(target=read_ready, daemon=True)
    reader.start()
    try:
        assert ready.wait(5) and messages == ["locked"]
        monkeypatch.setattr(cfg, "_LOCK_DEADLINE_SECONDS", 0.05)
        assert cfg.migrate_config_location() == str(target)
        assert source.read_bytes() == original and not target.exists()
        assert "Failed to migrate legacy config" in caplog.text
    finally:
        assert child.stdin is not None
        try:
            child.stdin.write("release\n")
            child.stdin.flush()
            child.wait(timeout=5)
        finally:
            if child.poll() is None:
                child.terminate()
                child.wait(timeout=5)
            reader.join(5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream is not None:
                    stream.close()
    assert child.returncode == 0
