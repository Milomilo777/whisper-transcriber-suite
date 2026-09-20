"""Fixpack regression tests for cluster ``proc_ckpt``.

Covers two closed holes plus one already-guarded candidate left as a
documented control:

  1. ``core._proc.kill_process_tree`` on POSIX with ``force=False`` now
     escalates SIGTERM -> SIGKILL when a wedged process group ignores the
     graceful signal (previously it sent SIGTERM once and returned, so a
     stuck ffmpeg/demucs grandchild survived).
  2. ``core._checkpoint.source_key`` is case-folded via ``os.path.normcase``
     so a checkpoint written for ``C:\\Foo.mp4`` is still found when the
     same file is reopened as ``c:\\foo.mp4`` on a case-insensitive FS.
  3. (control) the stat-failure write storing ``size=0`` does NOT falsely
     validate a real 0-byte source on resume — the ``or -1`` sentinel in
     ``validate_checkpoint`` already rejects it.

All hermetic: no network, no real model, no Tk root, no real process.
"""
from __future__ import annotations

import os
import signal
import time

import pytest

from core import _checkpoint, _proc


# --------------------------------------------------------------------------
# 1. POSIX graceful kill escalates to SIGKILL on a wedged group
# --------------------------------------------------------------------------


class _WedgedProc:
    """A process whose group ignores SIGTERM: poll() never reports exit."""

    def __init__(self, pid: int = 555) -> None:
        self.pid = pid
        self.terminated = False
        self.killed = False

    def poll(self):  # never exits -> forces the escalation path / timeout
        return None

    def terminate(self):
        self.terminated = True

    def kill(self):
        self.killed = True


class _GracefulProc:
    """A process that exits shortly after the first SIGTERM."""

    def __init__(self, pid: int = 777, exit_after_polls: int = 1) -> None:
        self.pid = pid
        self._polls = 0
        self._exit_after = exit_after_polls

    def poll(self):
        self._polls += 1
        return 0 if self._polls > self._exit_after else None

    def terminate(self):  # pragma: no cover - not used in the assertions
        pass

    def kill(self):  # pragma: no cover
        pass


# A sentinel distinct from SIGTERM so the escalation is observable even on
# Windows hosts where signal.SIGKILL does not exist. _proc reads SIGKILL via
# ``getattr(signal, "SIGKILL", signal.SIGTERM)`` against its module-level
# ``signal`` reference, so injecting it here drives the real code path.
_FAKE_SIGKILL = 9


def _force_posix(monkeypatch):
    """Drive the POSIX branch of kill_process_tree regardless of host OS.

    Forces ``os.name`` to posix, supplies ``getpgid``, and guarantees a
    SIGKILL distinct from SIGTERM so the SIGTERM->SIGKILL escalation is
    exercised on every host (Windows ``signal`` has no real SIGKILL).
    """
    monkeypatch.setattr(_proc.os, "name", "posix", raising=False)
    monkeypatch.setattr(_proc.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(_proc.signal, "SIGKILL", _FAKE_SIGKILL, raising=False)


def test_posix_graceful_escalates_to_sigkill(monkeypatch):
    """force=False on a group that ignores SIGTERM must follow up with
    SIGKILL after the grace period — the pre-fix code sent SIGTERM once
    and returned (the wedged child survived)."""
    _force_posix(monkeypatch)
    sigs: list = []
    monkeypatch.setattr(
        _proc.os, "killpg",
        lambda pgid, sig: sigs.append((pgid, sig)),
        raising=False,
    )
    # Keep the grace window tiny so the test is fast.
    proc = _WedgedProc(pid=555)
    _proc.kill_process_tree(proc, force=False, timeout=0.1)

    sent = [sig for _pgid, sig in sigs]
    assert signal.SIGTERM in sent, "graceful pass should send SIGTERM first"
    assert _FAKE_SIGKILL in sent, (
        "a wedged group ignoring SIGTERM must be escalated to SIGKILL"
    )
    # Order: SIGTERM strictly before SIGKILL.
    assert sent.index(signal.SIGTERM) < sent.index(_FAKE_SIGKILL)


def test_posix_graceful_no_sigkill_when_group_exits(monkeypatch):
    """If the group exits within the grace window, do NOT send SIGKILL —
    the graceful terminate is honoured."""
    _force_posix(monkeypatch)
    sigs: list = []
    monkeypatch.setattr(
        _proc.os, "killpg",
        lambda pgid, sig: sigs.append((pgid, sig)),
        raising=False,
    )
    proc = _GracefulProc(pid=777, exit_after_polls=1)
    _proc.kill_process_tree(proc, force=False, timeout=2.0)

    sent = [sig for _pgid, sig in sigs]
    assert sent == [signal.SIGTERM], (
        f"only SIGTERM expected once the group exits, got {sent!r}"
    )
    assert _FAKE_SIGKILL not in sent


def test_posix_force_sends_sigkill_once(monkeypatch):
    """force=True is the hard kill: a single SIGKILL, no escalation loop."""
    _force_posix(monkeypatch)
    sigs: list = []
    monkeypatch.setattr(
        _proc.os, "killpg",
        lambda pgid, sig: sigs.append((pgid, sig)),
        raising=False,
    )
    proc = _WedgedProc(pid=999)
    _proc.kill_process_tree(proc, force=True, timeout=5.0)

    sent = [sig for _pgid, sig in sigs]
    assert sent == [_FAKE_SIGKILL], (
        f"force=True should SIGKILL once, got {sent!r}"
    )


def test_wait_for_exit_returns_quickly_on_timeout():
    """_wait_for_exit must honour the timeout and never raise."""
    start = time.monotonic()
    out = _proc._wait_for_exit(_WedgedProc(), timeout=0.05)
    assert out is False
    assert (time.monotonic() - start) < 1.0


# --------------------------------------------------------------------------
# 2. checkpoint key is case-folded per the filesystem's semantics
# --------------------------------------------------------------------------


def test_source_key_uses_normcase(monkeypatch):
    """On a case-insensitive FS (normcase lowercases), differing-case
    paths for the same file must hash to the SAME key so resume finds
    the checkpoint. We force Windows-style normcase to make the test
    deterministic on any host."""
    monkeypatch.setattr(_checkpoint.os.path, "normcase", lambda p: p.lower())
    # Absolutise consistently so only the case differs between the two.
    monkeypatch.setattr(_checkpoint.os.path, "abspath", lambda p: p)

    k_upper = _checkpoint.source_key("C:\\Media\\Foo.MP4")
    k_lower = _checkpoint.source_key("c:\\media\\foo.mp4")
    assert k_upper == k_lower, (
        "case-insensitive FS: differing-case paths must share one key"
    )


def test_source_key_case_sensitive_keeps_distinct(monkeypatch):
    """On a case-sensitive FS (normcase is identity) two genuinely
    distinct files differing only in case keep distinct keys."""
    monkeypatch.setattr(_checkpoint.os.path, "normcase", lambda p: p)
    monkeypatch.setattr(_checkpoint.os.path, "abspath", lambda p: p)

    k1 = _checkpoint.source_key("/data/Foo.mp4")
    k2 = _checkpoint.source_key("/data/foo.mp4")
    assert k1 != k2, "case-sensitive FS must not collide distinct files"


# --------------------------------------------------------------------------
# 3. (control) stat-failure 0/0 does NOT validate a real 0-byte source
# --------------------------------------------------------------------------


def test_zero_byte_source_not_validated_after_stat_failure(tmp_path, monkeypatch):
    """A checkpoint written while the source could not be stat'd stores
    size=0/mtime=0. On resume against a real 0-byte source, validation
    must STILL refuse (the `or -1` sentinel guards this), proving the
    falsely-validates-0-byte hole is already closed."""
    # Redirect partials_dir into tmp so we don't touch the user profile.
    monkeypatch.setattr(_checkpoint, "user_data_dir", lambda: tmp_path)

    src = tmp_path / "empty.wav"
    src.write_bytes(b"")  # genuinely 0 bytes
    assert src.stat().st_size == 0

    # Simulate the write-time stat failure: store size=0 / mtime=0.
    data = {
        "schema_version": _checkpoint.SCHEMA_VERSION,
        "source_path": str(src),
        "source_size": 0,
        "source_mtime": 0.0,
        "model_name": "m",
        "backend": "faster_whisper",
        "language": "en",
        "language_probability": 0.9,
        "config_fingerprint": "fp",
        "last_end_time": 1.0,
        "segment_count": 1,
        "segments": [{"start": 0.0, "end": 1.0, "text": "x"}],
        "checkpoint_time": 0.0,
    }
    reason = _checkpoint.validate_checkpoint(
        data,
        backend="faster_whisper",
        model_name="m",
        cfg_fingerprint="fp",
    )
    assert reason, (
        "a stat-failure (size=0) checkpoint must NOT validate a 0-byte source"
    )
    assert "size" in reason.lower()


# --------------------------------------------------------------------------
# 4. a non-UTF-8 checkpoint file reads as "corrupt" (None), never raises
# --------------------------------------------------------------------------


def test_load_checkpoint_returns_none_on_non_utf8_corruption(tmp_path, monkeypatch):
    """``load_checkpoint`` documents "None if missing/corrupt". A file
    whose bytes are not valid UTF-8 raises ``UnicodeDecodeError`` inside
    ``json.load`` — a ``ValueError``, not a ``JSONDecodeError`` — which
    used to escape into ``resume_transcription`` and fail the task
    instead of silently falling back to a full re-transcribe."""
    monkeypatch.setattr(_checkpoint, "user_data_dir", lambda: tmp_path)

    src = tmp_path / "media.mp4"
    src.write_bytes(b"x" * 16)
    cp_path = _checkpoint.checkpoint_path(str(src))
    cp_path.write_bytes(b'\xff\xfe{"schema_version": 1}')  # invalid UTF-8

    assert _checkpoint.load_checkpoint(str(src)) is None
