"""Start-up sweep for what a cut install leaves in the extras folder.

An install merges its staged tree with ``os.replace`` and ``.<name>.bak-<pid>`` /
``.<name>.merge-<pid>`` helpers; ``pylibs-stage-*`` holds pip's output. A process that dies in
the middle (an exit after the bounded wait, a crash, power loss) leaves them behind, and a
package may be missing. The sweep restores or removes them for processes that are gone.
"""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

import pytest

from core import optional_deps

DEAD = 4_000_001
LIVE = 4_000_002


@pytest.fixture
def extras(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    root = tmp_path / "cache"
    folder = root / "pylibs"
    folder.mkdir(parents=True)
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(folder))
    monkeypatch.setattr(optional_deps, "_pid_alive", lambda pid: pid == LIVE)
    return folder


def _pkg(path: Path, text: str = "x") -> Path:
    path.mkdir(parents=True)
    (path / "__init__.py").write_text(text, encoding="utf-8")
    return path


def test_a_displaced_package_is_restored_when_its_destination_is_missing(extras: Path) -> None:
    # Cut between "move the live package aside" and "move the new one in".
    _pkg(extras / f".torch.bak-{DEAD}", "original")

    restored, removed = optional_deps.sweep_install_leftovers()

    assert (restored, removed) == (1, 0)
    assert (extras / "torch" / "__init__.py").read_text(encoding="utf-8") == "original"
    assert not (extras / f".torch.bak-{DEAD}").exists()


def test_a_backup_is_dropped_when_the_new_package_is_already_in_place(extras: Path) -> None:
    _pkg(extras / "torch", "new")
    _pkg(extras / f".torch.bak-{DEAD}", "old")

    assert optional_deps.sweep_install_leftovers() == (0, 1)

    assert (extras / "torch" / "__init__.py").read_text(encoding="utf-8") == "new"
    assert not (extras / f".torch.bak-{DEAD}").exists()


def test_a_half_copied_merge_folder_and_file_are_removed(extras: Path) -> None:
    _pkg(extras / f".torch.merge-{DEAD}")
    (extras / f".six.py.merge-{DEAD}").write_text("partial", encoding="utf-8")

    assert optional_deps.sweep_install_leftovers() == (0, 2)
    assert [p.name for p in extras.iterdir()] == [".install.lock"]  # the lock file stays


def test_leftovers_of_a_living_process_are_not_touched(extras: Path) -> None:
    _pkg(extras / f".torch.bak-{LIVE}")
    _pkg(extras / f".torch.merge-{LIVE}")

    assert optional_deps.sweep_install_leftovers() == (0, 0)
    assert (extras / f".torch.bak-{LIVE}").is_dir() and (extras / f".torch.merge-{LIVE}").is_dir()


def test_leftovers_inside_a_shared_folder_are_found(extras: Path) -> None:
    shared = extras / "nvidia"  # no __init__.py: several installs add to it
    _pkg(shared / "cudnn")
    _pkg(shared / f".cublas.bak-{DEAD}", "cublas")

    assert optional_deps.sweep_install_leftovers() == (1, 0)
    assert (shared / "cublas" / "__init__.py").read_text(encoding="utf-8") == "cublas"


def test_a_real_package_is_not_searched_and_user_files_stay(extras: Path) -> None:
    pkg = _pkg(extras / "torch", "real package with code" + " " * 3)
    (pkg / "mod.py").write_text("x", encoding="utf-8")
    inside = _pkg(pkg / f".odd.bak-{DEAD}")  # not a merge location: left alone
    (extras / ".hidden").write_text("mine", encoding="utf-8")
    (extras / "notes.bak-123").write_text("mine", encoding="utf-8")  # no leading dot
    (extras / ".install.lock").write_bytes(b"")

    assert optional_deps.sweep_install_leftovers() == (0, 0)

    assert inside.is_dir()
    assert (extras / ".hidden").exists() and (extras / "notes.bak-123").exists()
    assert (extras / ".install.lock").exists()


def test_stale_staging_folders_next_to_the_extras_are_removed_nothing_else(extras: Path) -> None:
    cache = extras.parent
    _pkg(cache / "pylibs-stage-abc123" / "pkg")
    (cache / "pylibs-stage-def456").mkdir()
    keep = cache / "models"
    keep.mkdir()
    (cache / "pylibs-stage-file.txt").write_text("not a folder", encoding="utf-8")

    restored, removed = optional_deps.sweep_install_leftovers()

    assert (restored, removed) == (0, 2)
    assert not (cache / "pylibs-stage-abc123").exists()
    assert keep.is_dir() and extras.is_dir()
    assert (cache / "pylibs-stage-file.txt").exists()


def test_nothing_is_touched_while_another_install_holds_the_lock(
    extras: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import contextlib

    @contextlib.contextmanager
    def _busy(*_a: Any, **_k: Any) -> Any:
        yield ""  # the install lock is held elsewhere

    monkeypatch.setattr(optional_deps, "_extras_file_lock", _busy)
    _pkg(extras / f".torch.merge-{DEAD}")
    _pkg(extras.parent / "pylibs-stage-live")

    assert optional_deps.sweep_install_leftovers() == (0, 0)
    assert (extras / f".torch.merge-{DEAD}").exists()
    assert (extras.parent / "pylibs-stage-live").exists()


def test_a_missing_extras_folder_is_fine(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    monkeypatch.setattr(optional_deps, "extras_dir", lambda: str(tmp_path / "nope" / "pylibs"))
    assert optional_deps.sweep_install_leftovers() == (0, 0)


def test_an_unrestorable_backup_is_kept_not_deleted(
    extras: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _pkg(extras / f".torch.bak-{DEAD}", "original")

    def _fail(src: Any, dst: Any) -> None:
        raise PermissionError(13, "locked")

    monkeypatch.setattr(optional_deps.os, "replace", _fail)

    assert optional_deps.sweep_install_leftovers() == (0, 0)
    assert (extras / f".torch.bak-{DEAD}" / "__init__.py").exists()  # nothing lost


def test_pid_alive_tells_a_running_process_from_a_finished_one() -> None:
    import os

    assert optional_deps._pid_alive(os.getpid()) is True
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait(30)
    assert optional_deps._pid_alive(done.pid) is False


def test_the_sweep_is_started_off_the_ui_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    ran: list[str] = []
    done = threading.Event()

    def _sweep() -> tuple[int, int]:
        ran.append(threading.current_thread().name)
        done.set()
        return (0, 0)

    monkeypatch.setattr(optional_deps, "sweep_install_leftovers", _sweep)

    optional_deps.start_leftover_sweep()

    assert done.wait(10)
    assert ran and ran[0] != threading.main_thread().name


def test_a_failing_sweep_never_raises_into_the_start_up(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture,
) -> None:
    done = threading.Event()

    def _boom() -> tuple[int, int]:
        done.set()
        raise RuntimeError("scan failed")

    monkeypatch.setattr(optional_deps, "sweep_install_leftovers", _boom)

    optional_deps.start_leftover_sweep()

    assert done.wait(10)
