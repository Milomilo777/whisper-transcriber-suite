"""Checkpoint durability: a write that reports success must never destroy
the previous good checkpoint, and the resume path must fall back to a
re-run instead of raising (core._checkpoint's contract). Hermetic: real
files under tmp_path, no network, no model.

Covers the defect-hunt findings D1 (transient stat failure poisons the
checkpoint, resume then deletes it), D2 (a source path with a lone
surrogate breaks every write), D3 (_flush_to_disk swallowing a failed
flush publishes an empty file), D4 (junk field types raise out of
validate_checkpoint instead of refusing) and D5 (a read-only profile
dir makes the read paths raise).
"""
from __future__ import annotations

import copy
import json
import os

import pytest

from core import _checkpoint as cp
from core._checkpoint import (
    SCHEMA_VERSION,
    load_checkpoint,
    validate_checkpoint,
    write_checkpoint,
)


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cp, "user_data_dir", lambda: tmp_path / "data")
    return tmp_path / "data"


@pytest.fixture
def source(tmp_path):
    p = tmp_path / "audio.wav"
    p.write_bytes(b"0123456789")
    return p


def _write(src, **overrides):
    kwargs = dict(
        backend="b", model_name="m", language="en", language_probability=0.9,
        cfg_fingerprint="c", last_end_time=1.0, segments=[],
        checkpoint_time=1000.0,
    )
    kwargs.update(overrides)
    return write_checkpoint(str(src), **kwargs)


def _validate(src, data):
    return validate_checkpoint(
        data, backend="b", model_name="m", cfg_fingerprint="c")


def test_transient_stat_failure_keeps_the_checkpoint_resumable(
        data_dir, source, monkeypatch):
    _write(source)
    real_stat = os.stat

    def _blip(path, *a, **kw):
        raise OSError(116, "share hiccup")

    monkeypatch.setattr(cp.os, "stat", _blip)
    # A momentary source-stat failure during a periodic write: the write
    # must still succeed (the segments are paid for) without poisoning it.
    _write(source)
    monkeypatch.setattr(cp.os, "stat", real_stat)

    data = load_checkpoint(str(source))
    assert data is not None
    # The resume must NOT refuse with "size has changed" (the caller
    # deletes the partial on refusal — that destroyed the captured work).
    assert _validate(source, data) == ""


def test_stat_failure_stores_no_verification_fields(data_dir, source, monkeypatch):
    def _blip(path, *a, **kw):
        raise OSError(116, "share hiccup")

    monkeypatch.setattr(cp.os, "stat", _blip)
    _write(source)
    data = load_checkpoint(str(source))
    assert data["source_size"] is None
    assert data["source_mtime"] is None


def test_source_path_with_a_lone_surrogate_round_trips(data_dir, tmp_path):
    src = tmp_path / "bad\ud800name.wav"
    src.write_bytes(b"0123456789")
    # Every periodic write of the whole run used to raise
    # UnicodeEncodeError here; the transcriber then disabled checkpoints.
    path = _write(src)
    assert path.exists()
    data = load_checkpoint(str(src))
    assert data is not None
    assert data["segments"] == []
    assert _validate(src, data) == ""


def test_flush_failure_propagates_instead_of_publishing(data_dir, source, monkeypatch):
    class _DeadFlush:
        def flush(self):
            raise OSError(28, "no space left on device")

        def fileno(self):
            return 1  # fsync on fd 1 may work or fail; flush raises first

    # _flush_to_disk's contract: fsync problems are swallowed (exotic
    # filesystems), but a failed flush means the data never reached the
    # OS — that must propagate so the write counts as failed.
    fake = _DeadFlush()
    with pytest.raises(OSError):
        cp._flush_to_disk(fake)


def test_validate_survives_junk_field_types(data_dir, source):
    _write(source)
    data = load_checkpoint(str(source))
    for field in ("source_size", "source_mtime"):
        junk = copy.deepcopy(data)
        junk[field] = {"injected": True}
        reason = _validate(source, junk)
        assert isinstance(reason, str) and reason, field
    reason = _validate(source, {"schema_version": SCHEMA_VERSION})
    assert reason  # missing fields refuse too, never raise


def test_read_only_profile_dir_reads_are_safe(data_dir, monkeypatch):
    # A file occupying the data path (or an ACL): the READ paths
    # (has/load/sweep) must degrade to "no checkpoint", not raise into
    # the resume menu.
    blocker = data_dir.parent / "blocked"
    monkeypatch.setattr(cp, "user_data_dir", lambda: blocker)
    blocker.write_text("a file, not a directory", encoding="utf-8")
    assert cp.has_checkpoint("x.wav") is False
    assert load_checkpoint("x.wav") is None
    assert cp.sweep_partials() == 0


def test_write_still_creates_a_missing_partials_dir(data_dir, source):
    # The read paths no longer mkdir, but a WRITE into a fresh profile
    # must still create user_data_dir/partials itself.
    assert not (data_dir / "partials").exists()
    _write(source)
    assert (data_dir / "partials").is_dir()
    assert load_checkpoint(str(source)) is not None
