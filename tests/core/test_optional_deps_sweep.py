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


# ------------------------------------- links: nothing outside the extras folder is touched


def _make_link(link: Path, target: Path) -> bool:
    """A directory link: a junction on Windows (no privilege needed), else a symlink."""
    if sys.platform == "win32":
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)],
                              capture_output=True, text=True)
        return done.returncode == 0
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError:
        return False
    return True


def _outside(tmp_path: Path) -> Path:
    outside = tmp_path / "OUTSIDE"
    (outside / "precious").mkdir(parents=True)
    (outside / "precious" / "data.txt").write_text("PRECIOUS", encoding="utf-8")
    return outside


def test_a_linked_shared_folder_is_not_entered(extras: Path, tmp_path: Path) -> None:
    """`mklink /J pylibs\nvidia elsewhere`: leftover-named entries over there are not ours."""
    outside = _outside(tmp_path)
    _pkg(outside / f".cublas.bak-{DEAD}", "outside")
    (outside / f".thing.merge-{DEAD}").mkdir()
    if not _make_link(extras / "nvidia", outside):
        pytest.skip("cannot create a directory link here")

    assert optional_deps.sweep_install_leftovers() == (0, 0)

    assert (outside / f".cublas.bak-{DEAD}" / "__init__.py").exists()  # not moved
    assert (outside / f".thing.merge-{DEAD}").is_dir()  # not deleted
    assert not (outside / "cublas").exists()
    assert (outside / "precious" / "data.txt").read_text(encoding="utf-8") == "PRECIOUS"


def test_a_leftover_named_link_is_left_alone(extras: Path, tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    if not _make_link(extras / f".evil.bak-{DEAD}", outside):
        pytest.skip("cannot create a directory link here")

    assert optional_deps.sweep_install_leftovers() == (0, 0)

    assert (outside / "precious" / "data.txt").read_text(encoding="utf-8") == "PRECIOUS"
    assert not (extras / "evil").exists()


def test_a_linked_staging_folder_is_left_alone(extras: Path, tmp_path: Path) -> None:
    outside = _outside(tmp_path)
    if not _make_link(extras.parent / "pylibs-stage-link", outside):
        pytest.skip("cannot create a directory link here")

    assert optional_deps.sweep_install_leftovers() == (0, 0)

    assert (outside / "precious" / "data.txt").read_text(encoding="utf-8") == "PRECIOUS"


def test_is_reparse_point_sees_junctions_symlinks_and_plain_folders(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    target = _outside(tmp_path)
    link = tmp_path / "link"
    assert optional_deps._is_reparse_point(str(plain)) is False
    assert optional_deps._is_reparse_point(str(tmp_path / "missing")) is False
    if _make_link(link, target):
        assert optional_deps._is_reparse_point(str(link)) is True


# --------------------------- the lock must really be held, or the sweep does nothing


def test_a_lock_file_that_cannot_be_opened_stops_the_sweep(extras: Path) -> None:
    """The install lock is the only protection of a running install's staging folder."""
    (extras / ".install.lock").mkdir()  # opening it as a file fails
    live_stage = _pkg(extras.parent / "pylibs-stage-LIVE" / "pkg")
    _pkg(extras / f".torch.merge-{DEAD}")

    assert optional_deps.sweep_install_leftovers() == (0, 0)

    assert live_stage.is_dir() and (extras / f".torch.merge-{DEAD}").is_dir()


def test_a_lock_that_cannot_be_taken_for_another_reason_stops_the_sweep(
    extras: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    live_stage = _pkg(extras.parent / "pylibs-stage-LIVE" / "pkg")
    monkeypatch.setattr("core.config._lock_is_contended", lambda _e: False)
    if sys.platform == "win32":
        import msvcrt

        def _fail(*_a: Any) -> None:
            raise OSError(5, "Access is denied")

        monkeypatch.setattr(msvcrt, "locking", _fail)
    else:
        import fcntl

        def _fail(*_a: Any) -> None:
            raise OSError(5, "Input/output error")

        monkeypatch.setattr(fcntl, "flock", _fail)

    assert optional_deps.sweep_install_leftovers() == (0, 0)
    assert live_stage.is_dir()


def test_an_install_still_goes_ahead_without_a_usable_lock(
    extras: Path,
) -> None:
    """Only the sweep is strict; install() keeps its documented 'install without it'."""
    (extras / ".install.lock").mkdir()
    with optional_deps._extras_file_lock(str(extras), None, 1.0, None) as got:
        assert got == "free"


# ------------------------------------------------------------------ small hardening


def test_an_unreadable_folder_does_not_abort_the_whole_sweep(
    extras: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    (extras / "nvidia").mkdir()
    _pkg(extras / f".torch.bak-{DEAD}", "original")
    real = optional_deps.os.listdir

    def _listdir(path: Any = ".") -> list[str]:
        if str(path).endswith("nvidia"):
            raise PermissionError(13, "denied")
        return real(path)

    monkeypatch.setattr(optional_deps.os, "listdir", _listdir)
    # the empty-__init__ branch lists the folder: make nvidia look like one
    (extras / "nvidia" / "__init__.py").write_text("", encoding="utf-8")

    assert optional_deps.sweep_install_leftovers() == (1, 0)
    assert (extras / "torch" / "__init__.py").exists()


def test_a_cleaned_up_install_tells_the_user_how_to_repair(
    extras: Path, caplog: pytest.LogCaptureFixture,
) -> None:
    import logging

    _pkg(extras / f".torch.bak-{DEAD}", "original")
    with caplog.at_level(logging.WARNING, logger="core.optional_deps"):
        optional_deps.sweep_install_leftovers()

    assert any("install" in r.getMessage() and "again" in r.getMessage()
               for r in caplog.records if r.levelno >= logging.WARNING)
