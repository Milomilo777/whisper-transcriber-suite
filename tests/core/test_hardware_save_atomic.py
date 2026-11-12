"""Saving hardware choices uses a private staging file for each caller (no Tk)."""
import errno
import json
from pathlib import Path
import threading

import pytest

from core import hardware as hw


def tier(device):
    return hw.Tier(slug=device, label=device, device=device, compute_type="int8")


@pytest.fixture
def target(tmp_path, monkeypatch):
    path = tmp_path / "hardware.json"
    path.write_text('{"device":"previous"}', encoding="utf-8")
    monkeypatch.setattr(hw, "hardware_json_path", lambda: path)
    return path


@pytest.mark.parametrize("second_fails", [False, True])
def test_overlapping_save_cannot_remove_or_take_another_staging_file(target, monkeypatch, second_fails):
    sync = hw.os.fsync
    first_flushed, release_first = threading.Event(), threading.Event()
    results, failures = [], []

    def interleave(fd):
        if threading.current_thread().name == "wts-hardware-first":
            first_flushed.set()
            if not release_first.wait(5):
                raise RuntimeError("synthetic test synchronization timed out")
        elif second_fails:
            raise OSError(errno.ENOSPC, "synthetic second writer sync failure")
        return sync(fd)

    def first_save():
        try:
            results.append(hw.save_hardware_choice(tier("first")))
        except BaseException as error:
            failures.append(error)

    monkeypatch.setattr(hw.os, "fsync", interleave)
    worker = threading.Thread(target=first_save, name="wts-hardware-first")
    worker.start()
    try:
        assert first_flushed.wait(5)
        if second_fails:
            with pytest.raises(OSError, match="second writer sync failure"):
                hw.save_hardware_choice(tier("second"))
        else:
            assert hw.save_hardware_choice(tier("second")) == target
    finally:
        release_first.set()
        worker.join(5)
    assert not worker.is_alive()
    assert failures == [], "a healthy writer must retain its own staging file"
    assert results == [target]
    assert json.loads(target.read_text(encoding="utf-8"))["device"] == "first"
    assert not list(target.parent.glob(".hardware-*.tmp"))


def test_save_preserves_preexisting_fixed_temp_file(target):
    leftover = Path(str(target) + ".tmp")
    original = b'{"device":"recoverable previous attempt"}'
    leftover.write_bytes(original)
    assert hw.save_hardware_choice(tier("new")) == target
    assert leftover.read_bytes() == original
    assert json.loads(target.read_text(encoding="utf-8"))["device"] == "new"


@pytest.mark.parametrize("stage", ["sync", "publish"])
def test_failed_save_preserves_previous_choice_and_cleans_only_own_temp(target, monkeypatch, stage):
    original = target.read_bytes()
    unrelated = target.parent / ".hardware-unrelated.tmp"
    unrelated.write_bytes(b"retained unrelated copy")

    def fail(*args, **kwargs):
        raise OSError(errno.EIO, "synthetic hardware save failure")

    monkeypatch.setattr(hw.os, "fsync" if stage == "sync" else "replace", fail)
    with pytest.raises(OSError, match="hardware save failure"):
        hw.save_hardware_choice(tier("new"))
    assert target.read_bytes() == original
    assert unrelated.read_bytes() == b"retained unrelated copy"
    assert list(target.parent.glob(".hardware-*.tmp")) == [unrelated]
